from __future__ import annotations

from pathlib import Path
from typing import Any

from mpres.marp_source import parse_deck
from mpres.util import MPresError, read_yaml, relative_display


def validate_slide_density(source: Path) -> dict[str, Any]:
    audit_path = source / "SLIDE-DENSITY-AUDIT.yaml"
    if not audit_path.is_file():
        return {
            "schema_version": 1,
            "source": relative_display(audit_path, source),
            "errors": ["SLIDE-DENSITY-AUDIT.yaml is missing."],
            "warnings": [],
            "success": False,
        }
    value = read_yaml(audit_path)
    if not isinstance(value, dict) or not isinstance(value.get("slides"), list):
        raise MPresError("SLIDE-DENSITY-AUDIT.yaml must contain a slides list.")
    rows = value["slides"]
    if any(not isinstance(item, dict) for item in rows):
        raise MPresError("Every slide-density row must be a mapping.")
    deck = parse_deck(source / "presentation.md")
    source_ids = [slide.slide_id for slide in deck.slides if slide.slide_id]
    rows_by_id: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    warnings: list[str] = []
    for row in rows:
        slide_id = str(row.get("id") or "").strip()
        if not slide_id:
            errors.append("A density row is missing its slide id.")
            continue
        if slide_id in rows_by_id:
            errors.append(f"Duplicate density row: {slide_id}")
            continue
        rows_by_id[slide_id] = row
        move = str(row.get("principal_teaching_move") or "").strip()
        blocks = row.get("substantial_blocks")
        rationale = str(row.get("split_rationale") or "").strip()
        if len(move) < 8:
            errors.append(f"Slide {slide_id} needs a substantive principal_teaching_move.")
        if not isinstance(blocks, list) or not blocks:
            errors.append(f"Slide {slide_id} needs a non-empty substantial_blocks list.")
            block_count = 0
        else:
            block_count = len(blocks)
            if any(not str(item).strip() for item in blocks):
                errors.append(f"Slide {slide_id} contains an empty substantial block label.")
        if block_count > 3 and not rationale:
            errors.append(
                f"Slide {slide_id} has {block_count} substantial blocks without split_rationale."
            )
        elif block_count > 2 and not rationale:
            warnings.append(
                f"Slide {slide_id} has {block_count} substantial blocks; consider splitting or explain why they form one move."
            )
    missing = sorted(set(source_ids) - set(rows_by_id))
    extra = sorted(set(rows_by_id) - set(source_ids))
    if missing:
        errors.append("Slides missing from density audit: " + ", ".join(missing[:20]))
    if extra:
        errors.append("Density rows absent from source: " + ", ".join(extra[:20]))
    return {
        "schema_version": 1,
        "source": relative_display(audit_path, source),
        "slide_count": len(source_ids),
        "audited_slide_count": len(rows_by_id),
        "errors": errors,
        "warnings": warnings,
        "success": not errors,
    }
