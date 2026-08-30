from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from mpres.geogebra import validate_presentation_geogebra_registry
from mpres.util import MPresError, read_yaml, relative_display, task_path, write_json_atomic

SLIDE_ID_RE = re.compile(r"<!--\s*slide-id\s*:\s*([^>]+?)\s*-->", re.IGNORECASE)
CLASS_RE = re.compile(r"<!--\s*_class\s*:\s*([^>]+?)\s*-->", re.IGNORECASE)
HEADING_RE = re.compile(r"^#{1,3}\s+(.+?)\s*$", re.MULTILINE)
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
HTML_IMAGE_RE = re.compile(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"'][^>]*>", re.IGNORECASE)
BULLET_RE = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+", re.MULTILINE)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
HTML_TAG_RE = re.compile(r"<[^>]+>")
MATH_BLOCK_RE = re.compile(r"\$\$.*?\$\$", re.DOTALL)
INLINE_MATH_RE = re.compile(r"\$(?!\$).*?(?<!\$)\$", re.DOTALL)
REMOTE_RE = re.compile(r"^(?:https?:)?//", re.IGNORECASE)


@dataclass
class Slide:
    index: int
    slide_id: str | None
    classes: list[str]
    title: str | None
    source: str
    visible_text: str
    visible_characters: int
    bullets: int
    table_rows: int
    image_paths: list[str]


@dataclass
class Deck:
    frontmatter: dict[str, Any]
    slides: list[Slide]
    source_path: str


def _split_frontmatter(lines: list[str]) -> tuple[dict[str, Any], list[str]]:
    if not lines or lines[0].strip() != "---":
        raise MPresError("Canonical Marp source must begin with YAML frontmatter.")
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        raise MPresError("Marp YAML frontmatter is not closed.")
    import yaml

    try:
        value = yaml.safe_load("".join(lines[1:end])) or {}
    except yaml.YAMLError as exc:
        raise MPresError(f"Invalid Marp YAML frontmatter: {exc}") from exc
    if not isinstance(value, dict):
        raise MPresError("Marp YAML frontmatter must be a mapping.")
    return value, lines[end + 1 :]


def _split_slides(lines: list[str]) -> list[str]:
    slides: list[list[str]] = [[]]
    fence_marker: str | None = None
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if fence_marker is None:
                fence_marker = marker
            elif marker == fence_marker:
                fence_marker = None
            slides[-1].append(line)
            continue
        if fence_marker is None and line.strip() == "---":
            slides.append([])
        else:
            slides[-1].append(line)
    return ["".join(chunk).strip() for chunk in slides if "".join(chunk).strip()]


def _visible_text(source: str) -> str:
    text = COMMENT_RE.sub(" ", source)
    text = MARKDOWN_IMAGE_RE.sub(" ", text)
    text = HTML_IMAGE_RE.sub(" ", text)
    text = MATH_BLOCK_RE.sub(" MATH ", text)
    text = INLINE_MATH_RE.sub(" MATH ", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"~~~.*?~~~", " ", text, flags=re.DOTALL)
    text = re.sub(r"[#>*_`|\[\]()]+", " ", text)
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    return text


def _table_rows(source: str) -> int:
    count = 0
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 3:
            if re.fullmatch(r"[|:\-\s]+", stripped):
                continue
            count += 1
    return count


def _image_paths(source: str) -> list[str]:
    values = [*MARKDOWN_IMAGE_RE.findall(source), *HTML_IMAGE_RE.findall(source)]
    result: list[str] = []
    for value in values:
        cleaned = value.strip().strip("<>")
        if " " in cleaned and not cleaned.startswith(("data:", "http://", "https://", "//")):
            cleaned = cleaned.split()[0]
        result.append(unquote(cleaned))
    return result


def parse_deck(path: Path) -> Deck:
    path = path.resolve()
    text = path.read_text(encoding="utf-8")
    frontmatter, body_lines = _split_frontmatter(text.splitlines(keepends=True))
    raw_slides = _split_slides(body_lines)
    slides: list[Slide] = []
    for index, source in enumerate(raw_slides, start=1):
        slide_id_match = SLIDE_ID_RE.search(source)
        class_match = CLASS_RE.search(source)
        heading_match = HEADING_RE.search(source)
        visible = _visible_text(source)
        classes = class_match.group(1).split() if class_match else []
        slides.append(
            Slide(
                index=index,
                slide_id=slide_id_match.group(1).strip() if slide_id_match else None,
                classes=classes,
                title=heading_match.group(1).strip() if heading_match else None,
                source=source,
                visible_text=visible,
                visible_characters=len(visible),
                bullets=len(BULLET_RE.findall(source)),
                table_rows=_table_rows(source),
                image_paths=_image_paths(source),
            )
        )
    if not slides:
        raise MPresError("Marp source contains no slides.")
    return Deck(frontmatter=frontmatter, slides=slides, source_path=str(path))


def _manifest_check(source_root: Path, deck: Deck) -> dict[str, Any]:
    manifest_path = source_root / "DECK-MANIFEST.yaml"
    errors: list[str] = []
    warnings: list[str] = []
    if not manifest_path.is_file():
        return {"ok": False, "errors": ["DECK-MANIFEST.yaml is missing."], "warnings": []}
    manifest = read_yaml(manifest_path)
    if not isinstance(manifest, dict):
        return {"ok": False, "errors": ["DECK-MANIFEST.yaml must be a mapping."], "warnings": []}
    rows = manifest.get("slides") or []
    if not isinstance(rows, list):
        errors.append("DECK-MANIFEST.yaml slides must be a list.")
        rows = []
    manifest_ids = [str(item.get("id")) for item in rows if isinstance(item, dict) and item.get("id")]
    source_ids = [slide.slide_id for slide in deck.slides if slide.slide_id]
    missing_manifest = sorted(set(source_ids) - set(manifest_ids))
    missing_source = sorted(set(manifest_ids) - set(source_ids))
    if missing_manifest:
        errors.append("Slides missing from manifest: " + ", ".join(missing_manifest[:12]))
    if missing_source:
        errors.append("Manifest IDs missing from source: " + ", ".join(missing_source[:12]))
    kinds = [item.get("kind") for item in rows if isinstance(item, dict)]
    invalid_kinds = sorted({str(kind) for kind in kinds if kind not in {"core", "support"}})
    if invalid_kinds:
        errors.append("Invalid slide kinds: " + ", ".join(invalid_kinds))
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "manifest_slide_count": len(manifest_ids),
        "source_slide_count": len(source_ids),
        "core_count": sum(kind == "core" for kind in kinds),
        "support_count": sum(kind == "support" for kind in kinds),
    }


def lint_deck(
    source_root: Path,
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_root = source_root.resolve()
    deck_path = source_root / "presentation.md"
    if not deck_path.is_file():
        raise MPresError(f"Canonical Marp source is missing: {deck_path}")
    deck = parse_deck(deck_path)
    errors: list[str] = []
    warnings: list[str] = []
    front = deck.frontmatter
    required = {
        "marp": True,
        "theme": "mathist-academic",
        "paginate": True,
        "size": "16:9",
        "math": "mathjax",
    }
    for key, expected in required.items():
        if front.get(key) != expected:
            errors.append(f"Frontmatter {key!r} must be {expected!r}, got {front.get(key)!r}.")
    if "style" in front:
        errors.append("Inline frontmatter CSS is forbidden; use theme.css.")

    limits = (policy or {}).get("source_limits", {}) if isinstance(policy, dict) else {}
    warning_chars = int(limits.get("warning_visible_characters_per_slide", 650) or 650)
    error_chars = int(limits.get("error_visible_characters_per_slide", 1000) or 1000)
    warning_bullets = int(limits.get("warning_bullets_per_slide", 7) or 7)
    warning_rows = int(limits.get("warning_table_rows_per_slide", 9) or 9)

    ids: list[str] = []
    slide_reports: list[dict[str, Any]] = []
    for slide in deck.slides:
        slide_errors: list[str] = []
        slide_warnings: list[str] = []
        if not slide.slide_id:
            slide_errors.append("Missing <!-- slide-id: ... -->.")
        else:
            ids.append(slide.slide_id)
        if not ({"core", "support"} & set(slide.classes)):
            slide_errors.append("Slide class must include core or support.")
        if slide.visible_characters > error_chars:
            slide_errors.append(
                f"Visible text is too dense ({slide.visible_characters} characters > {error_chars})."
            )
        elif slide.visible_characters > warning_chars:
            slide_warnings.append(
                f"Visible text is dense ({slide.visible_characters} characters > {warning_chars})."
            )
        if slide.bullets > warning_bullets:
            slide_warnings.append(f"Slide has {slide.bullets} bullet/list items.")
        if slide.table_rows > warning_rows:
            slide_warnings.append(f"Slide table has {slide.table_rows} content rows.")
        if re.search(r"<\s*(?:script|iframe|object|embed)\b", slide.source, re.IGNORECASE):
            slide_errors.append("Executable or embedded HTML elements are forbidden.")
        if "<style" in slide.source.lower():
            slide_errors.append("Per-slide <style> blocks are forbidden; use theme.css.")
        for ref in slide.image_paths:
            if REMOTE_RE.match(ref) or ref.lower().startswith("data:"):
                slide_errors.append(f"Remote or embedded image is forbidden: {ref}")
                continue
            candidate = (source_root / ref).resolve()
            try:
                candidate.relative_to(source_root)
            except ValueError:
                slide_errors.append(f"Image path escapes source tree: {ref}")
                continue
            if not candidate.is_file():
                slide_errors.append(f"Referenced image is missing: {ref}")
        errors.extend(f"slide {slide.index} ({slide.slide_id or 'no-id'}): {msg}" for msg in slide_errors)
        warnings.extend(
            f"slide {slide.index} ({slide.slide_id or 'no-id'}): {msg}" for msg in slide_warnings
        )
        slide_reports.append(
            {
                **asdict(slide),
                "source": None,
                "errors": slide_errors,
                "warnings": slide_warnings,
            }
        )
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        errors.append("Duplicate slide IDs: " + ", ".join(duplicates))
    manifest = _manifest_check(source_root, deck)
    errors.extend(manifest["errors"])
    warnings.extend(manifest["warnings"])
    geogebra = validate_presentation_geogebra_registry(
        source_root,
        deck_path.read_text(encoding="utf-8"),
        maximum_selected_per_unit=int(
            (((policy or {}).get("online_resources") or {}).get("geogebra") or {}).get(
                "max_selected_links_per_unit", 3
            )
            or 3
        ),
    )
    errors.extend(geogebra["errors"])
    warnings.extend(geogebra["warnings"])
    theme = source_root / "theme.css"
    if not theme.is_file():
        errors.append("theme.css is missing.")
    else:
        theme_text = theme.read_text(encoding="utf-8", errors="replace")
        if "@theme mathist-academic" not in theme_text:
            errors.append("theme.css does not declare @theme mathist-academic.")
        if re.search(r"font-size\s*:\s*(?:[0-9]|1[0-5])px", theme_text, re.IGNORECASE):
            warnings.append("theme.css contains a font size below 16px; verify it is not student text.")
    return {
        "schema_version": 1,
        "source": str(deck_path),
        "frontmatter": deck.frontmatter,
        "slide_count": len(deck.slides),
        "slides": slide_reports,
        "manifest": manifest,
        "geogebra": geogebra,
        "errors": errors,
        "warnings": warnings,
        "success": not errors,
    }


def lint_task_source(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    stage: str = "author",
) -> dict[str, Any]:
    task = task_path(root, slug)
    if stage == "author":
        base = task / "workers" / "author-coordinator" / "drafts" / presentation_id
    elif stage == "release":
        base = task / "workers" / "release-coordinator" / "approved" / presentation_id
    else:
        raise MPresError("Source-lint stage must be author or release.")
    policy = read_yaml(task / "EXECUTION-POLICY.yaml") or {}
    report = lint_deck(base / "source", policy=policy)
    report_path = base / "build" / f"source-lint-{stage}.json"
    write_json_atomic(report_path, report)
    report["report_path"] = relative_display(report_path, root)
    return report
