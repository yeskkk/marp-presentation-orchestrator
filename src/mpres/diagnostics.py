from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

import yaml

from mpres.assignments import assignment_contract_status, scaffold_assignment_contract
from mpres.logs import append_log
from mpres.marp_source import Deck, Slide, parse_deck
from mpres.runtime_profile import load_runtime_profile, resolve_runtime
from mpres.state import get_presentation, load_state
from mpres.tasks import require_gate
from mpres.transactions import transactional_task_mutation
from mpres.util import (
    MPresError,
    ensure_within,
    make_tree_read_only,
    read_json,
    read_yaml,
    relative_display,
    safe_id,
    task_path,
    text_placeholders,
    utc_now,
    write_yaml_atomic,
)

DIAGNOSTIC_ROLE = "diagnostic-reviewer"
DIAGNOSTIC_ACTIONS = {
    "targeted_patch",
    "continue_current_authoring",
    "full_corrective_review",
    "open_larger_diagnostic_case",
    "no_change",
}
DIAGNOSTIC_CONFIDENCE = {"low", "medium", "high"}
MAX_TARGET_SLIDES = 8
MAX_NEIGHBOR_RADIUS = 2
MAX_INCLUDED_SLIDES = 20


def diagnostic_root(root: Path, slug: str) -> Path:
    return task_path(root, slug) / "diagnostics"


def diagnostic_case_root(
    root: Path, slug: str, presentation_id: str, case_id: str
) -> Path:
    safe_id(presentation_id, label="presentation ID")
    safe_id(case_id, label="diagnostic case ID")
    return diagnostic_root(root, slug) / presentation_id / case_id


def _next_case_id(root: Path, slug: str, presentation_id: str) -> str:
    parent = diagnostic_root(root, slug) / presentation_id
    used: set[int] = set()
    if parent.is_dir():
        for path in parent.iterdir():
            if path.is_dir() and path.name.startswith("d") and path.name[1:].isdigit():
                used.add(int(path.name[1:]))
    number = 1
    while number in used:
        number += 1
    return f"d{number:04d}"


def _current_published_source(
    root: Path, task: Path, presentation_id: str
) -> tuple[Path, Path, str]:
    marker = task / "deliverables" / presentation_id / "CURRENT-REVISION.json"
    if marker.is_file():
        value = read_json(marker)
        source_value = str(value.get("source") or "").strip()
        if not source_value:
            raise MPresError(f"Current revision marker lacks a source path: {marker}")
        source = (root / source_value).resolve()
        return source, source.parent, "published_current_revision"
    deliverable = task / "deliverables" / presentation_id
    return deliverable / "source", deliverable, "published_base_revision"


def _resolve_source_anchor(
    root: Path, slug: str, presentation_id: str
) -> tuple[Path, Path | None, str, str]:
    """Resolve the exact source state that existed when the case was opened.

    The returned source is copied only as a bounded slide subset. No PDF is
    copied or opened. The report root is used only for mechanically filtering
    already-existing source/layout gate output for the selected slides.
    """

    state = load_state(root, slug)
    presentation = get_presentation(state, presentation_id)
    task = task_path(root, slug)
    status = str(presentation.get("status") or "")
    maintenance = presentation.get("maintenance")
    if isinstance(maintenance, dict) and maintenance.get("status") not in {
        None,
        "published",
        "abandoned",
    }:
        revision = int(maintenance.get("revision") or 0)
        if revision < 1:
            raise MPresError("Active maintenance revision is malformed.")
        base = task / "maintenance" / presentation_id / f"r{revision:04d}"
        maintenance_status = str(maintenance.get("status") or "")
        frozen = base / "review" / "full" / "request" / "source"
        if maintenance_status in {"review_requested", "reviewing"} and frozen.is_dir():
            source = frozen
            source_kind = f"maintenance_r{revision:04d}_frozen_review"
        else:
            source = base / "source"
            source_kind = f"maintenance_r{revision:04d}_{maintenance_status or 'open'}"
        report_root = base / "build"
    elif status == "authoring":
        base = task / "workers" / "author-coordinator" / "drafts" / presentation_id
        source, report_root, source_kind = base / "source", base / "build", "authoring_draft"
    elif status in {"review_requested", "reviewing"}:
        source = task / "reviews" / presentation_id / "full" / "request" / "source"
        report_root = task / "workers" / "author-coordinator" / "drafts" / presentation_id / "build"
        source_kind = "frozen_full_review"
    elif status in {"author_revision", "release_ready"}:
        base = task / "workers" / "deck-revision-author" / "drafts" / presentation_id
        source, report_root = base / "source", base / "build"
        source_kind = "deck_revision_candidate"
        if not source.is_dir() and status == "release_ready":
            release = task / "control-plane" / "release" / presentation_id
            source, report_root, source_kind = (
                release / "source",
                release / "build",
                "release_ready_candidate",
            )
    elif status == "finalized":
        source, report_root, source_kind = _current_published_source(root, task, presentation_id)
    else:
        raise MPresError(
            f"Presentation {presentation_id} has no diagnosable Marp source in status {status!r}."
        )
    source = source.resolve()
    if not source.is_dir() or not (source / "presentation.md").is_file():
        raise MPresError(f"Diagnostic source is missing: {source}")
    return source, report_root.resolve() if report_root and report_root.exists() else None, source_kind, status


def _resolve_targets(
    deck: Deck,
    *,
    slide_ids: Iterable[str],
    page_numbers: Iterable[int],
) -> tuple[list[int], list[str], list[int]]:
    requested_ids = list(dict.fromkeys(str(item).strip() for item in slide_ids if str(item).strip()))
    requested_pages = list(dict.fromkeys(int(item) for item in page_numbers))
    if not requested_ids and not requested_pages:
        raise MPresError("A diagnostic case needs at least one --slide or --page target.")
    if len(requested_ids) + len(requested_pages) > MAX_TARGET_SLIDES:
        raise MPresError(
            f"The fast diagnostic path accepts at most {MAX_TARGET_SLIDES} target slides/pages. "
            "Open multiple cases or use a full corrective review for a broader problem."
        )
    id_to_index: dict[str, int] = {}
    duplicate_ids: set[str] = set()
    for index, slide in enumerate(deck.slides):
        if not slide.slide_id:
            continue
        if slide.slide_id in id_to_index:
            duplicate_ids.add(slide.slide_id)
        id_to_index[slide.slide_id] = index
    if duplicate_ids:
        raise MPresError("Diagnostic source contains duplicate slide IDs: " + ", ".join(sorted(duplicate_ids)))
    missing = [item for item in requested_ids if item not in id_to_index]
    if missing:
        raise MPresError("Unknown diagnostic slide IDs: " + ", ".join(missing))
    invalid_pages = [page for page in requested_pages if page < 1 or page > len(deck.slides)]
    if invalid_pages:
        raise MPresError(
            f"Diagnostic page numbers must be between 1 and {len(deck.slides)}: {invalid_pages}"
        )
    target_indexes: list[int] = []
    for slide_id in requested_ids:
        target_indexes.append(id_to_index[slide_id])
    for page in requested_pages:
        target_indexes.append(page - 1)
    target_indexes = list(dict.fromkeys(target_indexes))
    target_slide_ids: list[str] = []
    for index in target_indexes:
        slide_id = deck.slides[index].slide_id
        if not slide_id:
            raise MPresError(
                f"Page {index + 1} lacks a canonical slide ID; repair the source before diagnosis."
            )
        target_slide_ids.append(slide_id)
    return target_indexes, target_slide_ids, requested_pages


def _selected_indexes(target_indexes: list[int], slide_count: int, radius: int) -> list[int]:
    selected: set[int] = set()
    for index in target_indexes:
        selected.update(range(max(0, index - radius), min(slide_count, index + radius + 1)))
    result = sorted(selected)
    if len(result) > MAX_INCLUDED_SLIDES:
        raise MPresError(
            f"The requested targets and neighbors expand to {len(result)} slides; the fast path is capped "
            f"at {MAX_INCLUDED_SLIDES}. Open smaller cases or use a full corrective review."
        )
    return result


def _subset_markdown(deck: Deck, slides: list[Slide], *, case_id: str) -> str:
    frontmatter = yaml.safe_dump(deck.frontmatter, allow_unicode=True, sort_keys=False, width=1000).rstrip()
    header = (
        f"<!-- diagnostic-case: {case_id} -->\n"
        "<!-- read-only bounded evidence; never edit canonical presentation source from this file -->\n\n"
    )
    body = "\n\n---\n\n".join(slide.source.strip() for slide in slides)
    return f"---\n{frontmatter}\n---\n\n{header}{body}\n"


def _slide_index(
    deck: Deck,
    selected_indexes: list[int],
    target_indexes: list[int],
) -> list[dict[str, Any]]:
    target_set = set(target_indexes)
    rows: list[dict[str, Any]] = []
    for index in selected_indexes:
        slide = deck.slides[index]
        distance = min(abs(index - target) for target in target_indexes)
        rows.append(
            {
                "page": index + 1,
                "slide_id": slide.slide_id,
                "title": slide.title,
                "relationship": "target" if index in target_set else "neighbor",
                "distance_from_nearest_target": distance,
                "classes": slide.classes,
            }
        )
    return rows


def _selected_source_records(source: Path, selected_ids: set[str]) -> dict[str, Any]:
    result: dict[str, Any] = {"schema_version": 1, "records": {}}
    manifest_path = source / "DECK-MANIFEST.yaml"
    if manifest_path.is_file():
        manifest = read_yaml(manifest_path)
        if isinstance(manifest, dict):
            slides = [
                dict(row)
                for row in manifest.get("slides", [])
                if isinstance(row, dict) and str(row.get("id") or "") in selected_ids
            ]
            units = {str(row.get("unit")) for row in slides if row.get("unit")}
            content_units = [
                dict(row)
                for row in manifest.get("content_units", [])
                if isinstance(row, dict) and str(row.get("id") or "") in units
            ]
            result["records"]["deck_manifest"] = {
                "source": manifest_path.name,
                "presentation_id": manifest.get("presentation_id"),
                "content_units": content_units,
                "slides": slides,
            }
    interaction_path = source / "INTERACTION-RECORD.yaml"
    if interaction_path.is_file():
        interaction = read_yaml(interaction_path)
        if isinstance(interaction, dict):
            def touches(row: Mapping[str, Any]) -> bool:
                values = {
                    str(row.get("prompt_slide") or ""),
                    str(row.get("response_slide") or ""),
                    str(row.get("slide_id") or ""),
                }
                return bool(values & selected_ids)

            result["records"]["interactions"] = {
                "source": interaction_path.name,
                "interactions": [
                    dict(row)
                    for row in interaction.get("interactions", [])
                    if isinstance(row, Mapping) and touches(row)
                ],
                "mcq_items": [
                    dict(row)
                    for row in interaction.get("mcq_items", [])
                    if isinstance(row, Mapping) and touches(row)
                ],
            }
    density_path = source / "SLIDE-DENSITY-AUDIT.yaml"
    if density_path.is_file():
        density = read_yaml(density_path)
        if isinstance(density, dict):
            result["records"]["density"] = {
                "source": density_path.name,
                "slides": [
                    dict(row)
                    for row in density.get("slides", [])
                    if isinstance(row, dict) and str(row.get("id") or "") in selected_ids
                ],
            }
    return result


def _filter_gate_report(value: Mapping[str, Any], selected_ids: set[str]) -> dict[str, Any]:
    summary_keys = (
        "schema_version",
        "success",
        "pipeline",
        "presentation_id",
        "slide_count",
        "source_slide_count",
        "manifest_slide_count",
        "overflow_slide_count",
        "page_count",
    )
    result = {key: value[key] for key in summary_keys if key in value}
    for key in ("slides", "overflow_slides"):
        rows = value.get(key)
        if isinstance(rows, list):
            chosen = []
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                identifier = str(row.get("slide_id") or row.get("id") or "")
                if identifier in selected_ids:
                    chosen.append(dict(row))
            if chosen:
                result[key] = chosen
    for key in ("errors", "warnings"):
        rows = value.get(key)
        if isinstance(rows, list):
            chosen = [
                str(row)
                for row in rows
                if any(slide_id in str(row) for slide_id in selected_ids)
            ]
            if chosen:
                result[key] = chosen[:20]
    return result


def _gate_evidence(report_root: Path | None, selected_ids: set[str], root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": 1,
        "available": False,
        "reports": {},
        "policy": "existing machine-readable reports only; no PDF opening, screenshots, OCR, or model vision",
    }
    if report_root is None or not report_root.is_dir():
        return result
    names = (
        "source-lint*.json",
        "slide-density-audit*.json",
        "html-layout-inspection*.json",
        "pdf-inspection*.json",
        "render-report*.json",
    )
    paths: list[Path] = []
    for pattern in names:
        paths.extend(report_root.glob(pattern))
    for path in sorted(set(paths)):
        try:
            filtered = _filter_gate_report(read_json(path), selected_ids)
        except MPresError:
            continue
        if filtered:
            result["reports"][path.name] = {
                "source": relative_display(path, root),
                "selected_evidence": filtered,
            }
    result["available"] = bool(result["reports"])
    return result


def _diagnostic_assignment_text(
    root: Path,
    *,
    slug: str,
    presentation_id: str,
    case_id: str,
    user_report: str,
    evidence_root: Path,
    result_path: Path,
) -> str:
    template = (
        root / "templates" / "assignments" / "TASK-diagnostic-reviewer.template.md"
    ).read_text(encoding="utf-8")
    values = {
        "[[TASK_SLUG]]": slug,
        "[[PRESENTATION_ID]]": presentation_id,
        "[[CASE_ID]]": case_id,
        "[[USER_REPORT]]": user_report.strip(),
        "[[EVIDENCE_ROOT]]": relative_display(evidence_root, root),
        "[[RESULT_PATH]]": relative_display(result_path, root),
        "[[RUNTIME_PROFILE_PATH]]": f"tasks/{slug}/TASK-RUNTIME-PROFILE.yaml",
    }
    for old, new in values.items():
        template = template.replace(old, new)
    return template


@transactional_task_mutation
def open_diagnostic_case(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    user_report: str,
    slide_ids: list[str] | None = None,
    page_numbers: list[int] | None = None,
    neighbor_radius: int = 1,
    case_id: str | None = None,
) -> dict[str, Any]:
    """Create one bounded, read-only diagnosis from user-reported slide locations."""

    require_gate(root, slug, allow_engine_circuit=True)
    if len(user_report.strip()) < 20:
        raise MPresError("Diagnostic intake needs a substantive user report of at least 20 characters.")
    if isinstance(neighbor_radius, bool) or not 0 <= int(neighbor_radius) <= MAX_NEIGHBOR_RADIUS:
        raise MPresError(f"Neighbor radius must be between 0 and {MAX_NEIGHBOR_RADIUS}.")
    safe_id(presentation_id, label="presentation ID")
    case_id = safe_id(case_id, label="diagnostic case ID") if case_id else _next_case_id(
        root, slug, presentation_id
    )
    case_root = diagnostic_case_root(root, slug, presentation_id, case_id)
    if case_root.exists():
        raise MPresError(f"Diagnostic case already exists: {case_root}")

    source, report_root, source_kind, presentation_status = _resolve_source_anchor(
        root, slug, presentation_id
    )
    deck = parse_deck(source / "presentation.md")
    target_indexes, target_slide_ids, requested_pages = _resolve_targets(
        deck,
        slide_ids=slide_ids or [],
        page_numbers=page_numbers or [],
    )
    selected_indexes = _selected_indexes(target_indexes, len(deck.slides), int(neighbor_radius))
    selected_slides = [deck.slides[index] for index in selected_indexes]
    selected_ids = {str(slide.slide_id) for slide in selected_slides if slide.slide_id}
    index_rows = _slide_index(deck, selected_indexes, target_indexes)

    case_root.mkdir(parents=True, exist_ok=False)
    try:
        evidence = case_root / "evidence"
        response = case_root / "response"
        evidence.mkdir()
        response.mkdir()
        (evidence / "SLIDE-SUBSET.md").write_text(
            _subset_markdown(deck, selected_slides, case_id=case_id),
            encoding="utf-8",
            newline="\n",
        )
        write_yaml_atomic(
            evidence / "SLIDE-INDEX.yaml",
            {
                "schema_version": 1,
                "case_id": case_id,
                "presentation_id": presentation_id,
                "total_deck_slides": len(deck.slides),
                "target_slide_ids": target_slide_ids,
                "reported_pages": requested_pages,
                "neighbor_radius": int(neighbor_radius),
                "included_slides": index_rows,
            },
        )
        write_yaml_atomic(
            evidence / "SUPPORTING-RECORDS.yaml",
            _selected_source_records(source, selected_ids),
        )
        write_yaml_atomic(
            evidence / "GATE-EVIDENCE.yaml",
            _gate_evidence(report_root, selected_ids, root),
        )

        result_template = (
            root / "templates" / "structured" / "DIAGNOSTIC-RESULT.template.yaml"
        ).read_text(encoding="utf-8")
        for old, new in {
            "[[CASE_ID]]": case_id,
            "[[PRESENTATION_ID]]": presentation_id,
            "[[TARGET_SLIDE_ID]]": target_slide_ids[0],
        }.items():
            result_template = result_template.replace(old, new)
        result_path = response / "DIAGNOSTIC-RESULT.yaml"
        result_path.write_text(result_template, encoding="utf-8", newline="\n")

        assignment_path = case_root / "TASK-DIAGNOSTIC-REVIEWER.md"
        assignment_path.write_text(
            _diagnostic_assignment_text(
                root,
                slug=slug,
                presentation_id=presentation_id,
                case_id=case_id,
                user_report=user_report,
                evidence_root=evidence,
                result_path=result_path,
            ),
            encoding="utf-8",
            newline="\n",
        )
        scaffold_assignment_contract(
            root,
            assignment_path,
            assignment_id=f"{presentation_id}:diagnostic:{case_id}",
            role=DIAGNOSTIC_ROLE,
            presentation_id=presentation_id,
            requested_by="planner-from-user-feedback",
            need=(
                "Diagnose the user-reported problem from a bounded read-only slide subset, "
                "without editing source or widening context dynamically."
            ),
        )
        runtime = resolve_runtime(
            load_runtime_profile(root, slug),
            DIAGNOSTIC_ROLE,
            presentation_id=presentation_id,
        )
        case = {
            "schema_version": 1,
            "case_id": case_id,
            "task_slug": slug,
            "presentation_id": presentation_id,
            "classification": "presentation_defect",
            "status": "awaiting_diagnosis",
            "opened_utc": utc_now(),
            "user_report": user_report.strip(),
            "source_anchor": {
                "kind": source_kind,
                "presentation_status_when_opened": presentation_status,
                "canonical_source": relative_display(source, root),
                "copied_evidence_only": True,
                "hashes_generated": False,
            },
            "scope": {
                "target_slide_ids": target_slide_ids,
                "reported_pages": requested_pages,
                "neighbor_radius": int(neighbor_radius),
                "included_slide_ids": [row["slide_id"] for row in index_rows],
                "included_pages": [row["page"] for row in index_rows],
                "maximum_included_slides": MAX_INCLUDED_SLIDES,
            },
            "runtime": {
                **runtime,
                "selected_by": "user_in_TASK-RUNTIME-PROFILE_before_confirmation",
                "agent_may_change": False,
            },
            "permissions": {
                "diagnostic_worker": "read evidence; write only response/DIAGNOSTIC-RESULT.yaml",
                "canonical_source_edit": "forbidden",
                "automatic_patch": False,
                "automatic_scope_expansion": False,
                "pdf_opening_or_rendering": "forbidden",
                "screenshots_ocr_model_vision": "forbidden",
            },
            "paths": {
                "assignment": relative_display(assignment_path, root),
                "evidence": relative_display(evidence, root),
                "result": relative_display(result_path, root),
                "patch_scope": relative_display(case_root / "PATCH-SCOPE.yaml", root),
            },
        }
        write_yaml_atomic(case_root / "DIAGNOSTIC-CASE.yaml", case)
        make_tree_read_only(evidence)
    except Exception:
        if case_root.exists():
            shutil.rmtree(case_root, ignore_errors=True)
        raise

    append_log(
        root,
        slug,
        actor="planner",
        kind="diagnostic",
        presentation_id=presentation_id,
        message=(
            f"Opened read-only diagnostic case {case_id} for {len(target_slide_ids)} target "
            f"slide(s) and {len(selected_indexes)} bounded target/neighbor slides."
        ),
        data={
            "case": relative_display(case_root / "DIAGNOSTIC-CASE.yaml", root),
            "target_slide_ids": target_slide_ids,
            "included_slide_ids": [row["slide_id"] for row in index_rows],
        },
    )
    return {**case, "case_path": relative_display(case_root, root)}


def _substantive_text(value: Any, label: str, minimum: int = 12) -> str:
    text = str(value or "").strip()
    if len(text) < minimum:
        raise MPresError(f"Diagnostic result {label} must contain at least {minimum} characters.")
    return text


def _safe_relative_source_file(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(text)
    if not text or path.is_absolute() or ".." in path.parts:
        raise MPresError(f"Patch-scope file must be a safe source-relative path: {text!r}")
    return path.as_posix()


def _normalize_result(value: Any, case: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MPresError("DIAGNOSTIC-RESULT.yaml must contain a mapping.")
    if value.get("schema_version") != 1:
        raise MPresError("DIAGNOSTIC-RESULT.yaml schema_version must be 1.")
    if value.get("case_id") != case.get("case_id"):
        raise MPresError("Diagnostic result case_id does not match the case.")
    if value.get("presentation_id") != case.get("presentation_id"):
        raise MPresError("Diagnostic result presentation_id does not match the case.")
    if value.get("source_modified") is not False:
        raise MPresError("A diagnostic reviewer is read-only and must record source_modified: false.")
    confidence = str(value.get("confidence") or "").strip()
    if confidence not in DIAGNOSTIC_CONFIDENCE:
        raise MPresError(f"Diagnostic confidence must be one of {sorted(DIAGNOSTIC_CONFIDENCE)}.")
    action = str(value.get("recommended_action") or "").strip()
    if action not in DIAGNOSTIC_ACTIONS:
        raise MPresError(f"Diagnostic recommended_action must be one of {sorted(DIAGNOSTIC_ACTIONS)}.")
    expansion = value.get("scope_expansion_required")
    if not isinstance(expansion, bool):
        raise MPresError("scope_expansion_required must be true or false.")
    if expansion and action not in {"open_larger_diagnostic_case", "full_corrective_review"}:
        raise MPresError(
            "A result that needs more scope must recommend a larger diagnostic case or full corrective review."
        )

    included_ids = set((case.get("scope") or {}).get("included_slide_ids") or [])
    hypotheses_raw = value.get("root_cause_hypotheses")
    if not isinstance(hypotheses_raw, list) or not hypotheses_raw:
        raise MPresError("Diagnostic result needs at least one root-cause hypothesis.")
    hypotheses: list[dict[str, Any]] = []
    for index, row in enumerate(hypotheses_raw, start=1):
        if not isinstance(row, Mapping):
            raise MPresError(f"Root-cause hypothesis {index} must be a mapping.")
        evidence_raw = row.get("evidence")
        if not isinstance(evidence_raw, list) or not evidence_raw:
            raise MPresError(f"Root-cause hypothesis {index} needs slide-ID evidence.")
        evidence: list[dict[str, str]] = []
        for evidence_row in evidence_raw:
            if not isinstance(evidence_row, Mapping):
                raise MPresError("Every diagnostic evidence row must be a mapping.")
            slide_id = str(evidence_row.get("slide_id") or "").strip()
            if slide_id not in included_ids:
                raise MPresError(
                    f"Diagnostic evidence cites {slide_id!r}, which is outside the bounded evidence packet."
                )
            evidence.append(
                {
                    "slide_id": slide_id,
                    "observation": _substantive_text(
                        evidence_row.get("observation"), "evidence observation"
                    ),
                }
            )
        hypotheses.append(
            {
                "hypothesis": _substantive_text(row.get("hypothesis"), "root-cause hypothesis"),
                "evidence": evidence,
            }
        )

    affected_raw = value.get("affected_slide_ids") or []
    if not isinstance(affected_raw, list):
        raise MPresError("affected_slide_ids must be a list.")
    affected = list(dict.fromkeys(str(item).strip() for item in affected_raw if str(item).strip()))
    outside_affected = sorted(set(affected) - included_ids)
    if outside_affected:
        raise MPresError(
            "Affected slide IDs outside the bounded packet require a new case: "
            + ", ".join(outside_affected)
        )
    if action != "no_change" and not affected and not expansion:
        raise MPresError("A change recommendation needs affected_slide_ids or explicit scope expansion.")

    patch_raw = value.get("patch_scope") or {}
    if not isinstance(patch_raw, Mapping):
        raise MPresError("patch_scope must be a mapping.")
    patch_slide_ids = list(
        dict.fromkeys(str(item).strip() for item in patch_raw.get("slide_ids", []) if str(item).strip())
    )
    outside_patch = sorted(set(patch_slide_ids) - included_ids)
    if outside_patch:
        raise MPresError(
            "Proposed patch slide IDs exceed the evidence packet: " + ", ".join(outside_patch)
        )
    files_raw = patch_raw.get("files") or []
    if not isinstance(files_raw, list):
        raise MPresError("patch_scope.files must be a list.")
    files = list(dict.fromkeys(_safe_relative_source_file(item) for item in files_raw))

    def text_list(name: str, *, required: bool) -> list[str]:
        raw = patch_raw.get(name) or []
        if not isinstance(raw, list):
            raise MPresError(f"patch_scope.{name} must be a list.")
        rows = [_substantive_text(item, f"patch_scope.{name}", 8) for item in raw]
        if required and not rows:
            raise MPresError(f"patch_scope.{name} needs at least one item.")
        return rows

    patch_required = action in {"targeted_patch", "continue_current_authoring"} and not expansion
    if patch_required and (not patch_slide_ids or not files):
        raise MPresError("A bounded patch recommendation needs patch_scope.slide_ids and files.")
    normalized = {
        "schema_version": 1,
        "case_id": str(case["case_id"]),
        "presentation_id": str(case["presentation_id"]),
        "diagnostic_status": "complete",
        "summary": _substantive_text(value.get("summary"), "summary", 30),
        "root_cause_hypotheses": hypotheses,
        "confidence": confidence,
        "affected_slide_ids": affected,
        "scope_expansion_required": expansion,
        "recommended_action": action,
        "patch_scope": {
            "slide_ids": patch_slide_ids,
            "files": files,
            "permitted_changes": text_list("permitted_changes", required=patch_required),
            "forbidden_changes": text_list("forbidden_changes", required=patch_required),
            "regression_checks": text_list("regression_checks", required=patch_required),
        },
        "source_modified": False,
        "remaining_uncertainty": _substantive_text(
            value.get("remaining_uncertainty"), "remaining_uncertainty", 4
        ),
    }
    return normalized


@transactional_task_mutation
def submit_diagnostic_result(
    root: Path,
    slug: str,
    presentation_id: str,
    case_id: str,
    *,
    result_path: Path | None = None,
) -> dict[str, Any]:
    """Validate one read-only diagnosis and mechanically emit a proposed patch scope."""

    require_gate(root, slug, allow_engine_circuit=True)
    base = diagnostic_case_root(root, slug, presentation_id, case_id)
    case_path = base / "DIAGNOSTIC-CASE.yaml"
    case = read_yaml(case_path)
    if not isinstance(case, dict):
        raise MPresError(f"Diagnostic case is malformed: {case_path}")
    if case.get("status") != "awaiting_diagnosis":
        raise MPresError(f"Diagnostic case {case_id} is not awaiting a result.")
    assignment = base / "TASK-DIAGNOSTIC-REVIEWER.md"
    contract = assignment_contract_status(assignment)
    if not contract.get("approved") or text_placeholders(assignment):
        raise MPresError("The planner-written diagnostic assignment is incomplete or unapproved.")
    canonical_result = base / "response" / "DIAGNOSTIC-RESULT.yaml"
    submitted_path = (result_path or canonical_result).expanduser().resolve()
    ensure_within(submitted_path, base / "response", label="diagnostic result")
    if not submitted_path.is_file():
        raise MPresError(f"Diagnostic result is missing: {submitted_path}")
    placeholders = text_placeholders(submitted_path)
    if placeholders:
        raise MPresError(
            "Diagnostic result still contains placeholders: " + ", ".join(placeholders[:8])
        )
    result = _normalize_result(read_yaml(submitted_path), case)
    write_yaml_atomic(canonical_result, result)
    patch = result["patch_scope"]
    if result["scope_expansion_required"]:
        patch_status = "scope_expansion_required"
    elif result["recommended_action"] in {"targeted_patch", "continue_current_authoring"}:
        patch_status = "proposed_requires_planner_authorization"
    else:
        patch_status = "not_applicable"
    patch_record = {
        "schema_version": 1,
        "case_id": case_id,
        "presentation_id": presentation_id,
        "status": patch_status,
        "diagnostic_confidence": result["confidence"],
        "recommended_action": result["recommended_action"],
        "scope_expansion_required": result["scope_expansion_required"],
        "slide_ids": patch["slide_ids"],
        "files": patch["files"],
        "permitted_changes": patch["permitted_changes"],
        "forbidden_changes": patch["forbidden_changes"],
        "regression_checks": patch["regression_checks"],
        "planner_authorization_required": True,
        "automatic_source_edit": False,
        "full_deck_gate_after_any_patch": True,
        "created_utc": utc_now(),
    }
    write_yaml_atomic(base / "PATCH-SCOPE.yaml", patch_record)
    make_tree_read_only(base / "response")
    case["status"] = "completed"
    case["completed_utc"] = utc_now()
    case["diagnostic_summary"] = {
        "confidence": result["confidence"],
        "recommended_action": result["recommended_action"],
        "scope_expansion_required": result["scope_expansion_required"],
        "affected_slide_ids": result["affected_slide_ids"],
    }
    write_yaml_atomic(case_path, case)
    append_log(
        root,
        slug,
        actor=DIAGNOSTIC_ROLE,
        kind="diagnostic",
        presentation_id=presentation_id,
        message=(
            f"Completed read-only diagnostic case {case_id}; recommendation is "
            f"{result['recommended_action']} at {result['confidence']} confidence."
        ),
        data={
            "case": relative_display(case_path, root),
            "result": relative_display(canonical_result, root),
            "patch_scope": relative_display(base / "PATCH-SCOPE.yaml", root),
            "source_modified": False,
        },
    )
    return {
        "case": case,
        "result": result,
        "patch_scope": patch_record,
        "paths": {
            "case": relative_display(case_path, root),
            "result": relative_display(canonical_result, root),
            "patch_scope": relative_display(base / "PATCH-SCOPE.yaml", root),
        },
    }


def diagnostic_status(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    case_id: str | None = None,
) -> dict[str, Any]:
    safe_id(presentation_id, label="presentation ID")
    parent = diagnostic_root(root, slug) / presentation_id
    if case_id is not None:
        base = diagnostic_case_root(root, slug, presentation_id, case_id)
        case = read_yaml(base / "DIAGNOSTIC-CASE.yaml")
        if not isinstance(case, dict):
            raise MPresError(f"Diagnostic case is malformed: {base}")
        assignment = assignment_contract_status(base / "TASK-DIAGNOSTIC-REVIEWER.md")
        return {
            "case": case,
            "case_path": relative_display(base, root),
            "assignment_approved": assignment.get("approved") is True,
            "result_exists": (base / "response" / "DIAGNOSTIC-RESULT.yaml").is_file()
            and not text_placeholders(base / "response" / "DIAGNOSTIC-RESULT.yaml"),
            "patch_scope_exists": (base / "PATCH-SCOPE.yaml").is_file(),
        }
    cases: list[dict[str, Any]] = []
    if parent.is_dir():
        for base in sorted(path for path in parent.iterdir() if path.is_dir()):
            case_path = base / "DIAGNOSTIC-CASE.yaml"
            if not case_path.is_file():
                continue
            value = read_yaml(case_path)
            if isinstance(value, dict):
                cases.append(
                    {
                        "case_id": value.get("case_id"),
                        "status": value.get("status"),
                        "opened_utc": value.get("opened_utc"),
                        "target_slide_ids": (value.get("scope") or {}).get("target_slide_ids", []),
                        "recommended_action": (value.get("diagnostic_summary") or {}).get(
                            "recommended_action"
                        ),
                        "path": relative_display(base, root),
                    }
                )
    return {"presentation_id": presentation_id, "cases": cases, "case_count": len(cases)}
