from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _bbox_overlap_ratio(a: Any, b: Any) -> float:
    left = max(a.x0, b.x0)
    bottom = max(a.y0, b.y0)
    right = min(a.x1, b.x1)
    top = min(a.y1, b.y1)
    if right <= left or top <= bottom:
        return 0.0
    overlap = (right - left) * (top - bottom)
    smaller = min(max(0.0, a.width * a.height), max(0.0, b.width * b.height))
    return overlap / smaller if smaller else 0.0


def save_marp_figure(
    figure: Any,
    output_path: str | Path,
    report_path: str | Path,
    *,
    minimum_text_pt: float = 18.0,
    arrow_artists: list[Any] | None = None,
    asset_registry_path: str | None = None,
) -> dict[str, Any]:
    """Save an approved Matplotlib figure and write a structural readability report.

    The helper deliberately avoids rendering screenshots for review. It uses Matplotlib's own
    renderer to inspect artist bounds before writing SVG/PDF. Callers should use SVG for labelled
    diagrams and must pass arrow artists when arrows could obscure labels.
    """

    output = Path(output_path)
    report = Path(report_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    suffix = output.suffix.lower()
    if suffix not in {".svg", ".pdf", ".png"}:
        raise ValueError("Marp figure output must be SVG, PDF, or PNG.")
    figure.canvas.draw()
    renderer = figure.canvas.get_renderer()
    text_rows: list[dict[str, Any]] = []
    text_bboxes: list[Any] = []
    minimum_seen: float | None = None
    for text in figure.findobj(match=lambda artist: artist.__class__.__name__ == "Text"):
        content = str(text.get_text()).strip()
        if not content or not text.get_visible():
            continue
        size = float(text.get_fontsize())
        bbox = text.get_window_extent(renderer=renderer)
        text_bboxes.append(bbox)
        minimum_seen = size if minimum_seen is None else min(minimum_seen, size)
        text_rows.append(
            {
                "text": content,
                "font_pt": size,
                "bbox_pixels": [bbox.x0, bbox.y0, bbox.x1, bbox.y1],
            }
        )
    overlap_rows: list[dict[str, Any]] = []
    for index, arrow in enumerate(arrow_artists or []):
        try:
            bbox = arrow.get_window_extent(renderer=renderer)
        except Exception:
            continue
        for text_index, text_bbox in enumerate(text_bboxes):
            ratio = _bbox_overlap_ratio(bbox, text_bbox)
            if ratio > 0.08:
                overlap_rows.append(
                    {"arrow_index": index, "text_index": text_index, "overlap_ratio": ratio}
                )
    errors: list[str] = []
    if minimum_seen is not None and minimum_seen < minimum_text_pt:
        errors.append(
            f"Minimum figure text is {minimum_seen:.1f}pt; required minimum is {minimum_text_pt:.1f}pt."
        )
    if overlap_rows:
        errors.append(f"Detected {len(overlap_rows)} arrow/text overlap(s).")
    if suffix == ".png" and text_rows:
        errors.append("Raster output with text is forbidden; use SVG for labelled diagrams.")
    figure.savefig(output, bbox_inches="tight")
    result = {
        "schema_version": 1,
        "asset_path": asset_registry_path or output.as_posix(),
        "output_format": suffix.lstrip("."),
        "minimum_text_pt": minimum_seen,
        "required_minimum_text_pt": minimum_text_pt,
        "text_artists": text_rows,
        "arrow_text_overlap_count": len(overlap_rows),
        "arrow_text_overlaps": overlap_rows,
        "errors": errors,
        "success": not errors,
    }
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
