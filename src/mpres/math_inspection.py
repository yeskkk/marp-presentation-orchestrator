from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from mpres.marp_source import COMMENT_RE, FENCED_CODE_RE, INLINE_CODE_RE, MATH_FRAGMENT_RE, parse_deck
from mpres.util import relative_display

BEGIN_RE = re.compile(r"\\begin\{(?P<name>[A-Za-z*]+)\}")
END_RE = re.compile(r"\\end\{(?P<name>[A-Za-z*]+)\}")
COMMAND_RE = re.compile(r"\\(?P<name>[A-Za-z]+)")


def _masked(source: str) -> str:
    text = COMMENT_RE.sub(lambda match: "\n" * match.group(0).count("\n"), source)
    text = FENCED_CODE_RE.sub(lambda match: "\n" * match.group(0).count("\n"), text)
    return INLINE_CODE_RE.sub("", text)


def inspect_math_source(source: Path) -> dict[str, Any]:
    deck = parse_deck(source / "presentation.md")
    errors: list[str] = []
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []
    for slide in deck.slides:
        masked = _masked(slide.source)
        fragments = list(MATH_FRAGMENT_RE.finditer(masked))
        begins = [match.group("name") for match in BEGIN_RE.finditer(masked)]
        ends = [match.group("name") for match in END_RE.finditer(masked)]
        if begins != ends:
            errors.append(
                f"Slide {slide.slide_id or slide.index} has mismatched TeX environments: begin={begins}, end={ends}."
            )
        residue = MATH_FRAGMENT_RE.sub("", masked)
        suspicious = []
        for marker in ("$$", "\\[", "\\]", "\\(", "\\)"):
            if marker in residue:
                suspicious.append(marker)
        if suspicious:
            errors.append(
                f"Slide {slide.slide_id or slide.index} contains unmatched math delimiter marker(s): "
                + ", ".join(sorted(set(suspicious)))
            )
        commands = sorted({match.group("name") for match in COMMAND_RE.finditer(masked)})
        rows.append(
            {
                "slide_id": slide.slide_id or f"slide-{slide.index}",
                "fragment_count": len(fragments),
                "environments": begins,
                "commands": commands,
            }
        )
    return {
        "schema_version": 1,
        "source": relative_display(source / "presentation.md", source),
        "slides": rows,
        "total_fragments": sum(row["fragment_count"] for row in rows),
        "errors": errors,
        "warnings": warnings,
        "success": not errors,
        "scope_note": "Mechanical source inspection does not establish mathematical correctness.",
    }


def inspect_math_renderer(source_inventory: dict[str, Any], html_layout_report: dict[str, Any]) -> dict[str, Any]:
    expected = {
        str(row.get("slide_id")): int(row.get("fragment_count") or 0)
        for row in source_inventory.get("slides", [])
        if isinstance(row, dict)
    }
    renderer_rows = {
        str(row.get("id")): row
        for row in html_layout_report.get("math_renderer", [])
        if isinstance(row, dict)
    }
    errors: list[str] = []
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []
    for slide_id, expected_count in expected.items():
        rendered = renderer_rows.get(slide_id, {})
        rendered_count = int(rendered.get("rendered_math_nodes") or 0)
        renderer_errors = list(rendered.get("renderer_errors") or [])
        leaked = list(rendered.get("leaked_markers") or [])
        if expected_count > 0 and rendered_count == 0:
            errors.append(f"Slide {slide_id} contains source mathematics but no rendered math node.")
        if renderer_errors:
            errors.append(f"Slide {slide_id} contains renderer error nodes: {renderer_errors[:3]}")
        if leaked:
            errors.append(f"Slide {slide_id} leaks raw TeX/math markers into rendered text: {leaked[:5]}")
        if expected_count == 0 and rendered_count > 0:
            warnings.append(f"Slide {slide_id} has rendered math nodes not inventoried by source scanning.")
        rows.append(
            {
                "slide_id": slide_id,
                "source_fragment_count": expected_count,
                "rendered_math_nodes": rendered_count,
                "renderer_errors": renderer_errors,
                "leaked_markers": leaked,
            }
        )
    return {
        "schema_version": 1,
        "slides": rows,
        "errors": errors,
        "warnings": warnings,
        "success": not errors,
        "scope_note": "Renderer inspection does not establish mathematical correctness or notation consistency.",
    }
