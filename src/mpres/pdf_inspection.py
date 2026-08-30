from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import fitz
from pypdf import PdfReader

from mpres.marp_source import parse_deck
from mpres.util import MPresError, read_yaml, relative_display, task_path, write_json_atomic

INTERNAL_TERMS = (
    "worker1",
    "worker2",
    "review request",
    "finding registry",
    "build pipeline",
    "slide budget",
    "qmd",
    "quarto",
    "审核通道",
    "制作流程",
    "内部备注",
)


def _page_rect_contains(page_rect: fitz.Rect, bbox: fitz.Rect, tolerance: float = 1.5) -> bool:
    expanded = fitz.Rect(
        page_rect.x0 - tolerance,
        page_rect.y0 - tolerance,
        page_rect.x1 + tolerance,
        page_rect.y1 + tolerance,
    )
    return expanded.contains(bbox)


def inspect_pdf_file(
    pdf_path: Path,
    *,
    expected_pages: int | None = None,
    warning_min_text_pt: float = 12.0,
    error_min_text_pt: float = 8.0,
) -> dict[str, Any]:
    pdf_path = pdf_path.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    if not pdf_path.is_file():
        return {"success": False, "errors": [f"PDF does not exist: {pdf_path}"], "warnings": []}
    if pdf_path.stat().st_size < 1000:
        errors.append("PDF is implausibly small.")
    try:
        if pdf_path.read_bytes()[:5] != b"%PDF-":
            errors.append("File does not begin with a PDF header.")
        pypdf_reader = PdfReader(str(pdf_path))
        pypdf_pages = len(pypdf_reader.pages)
        metadata = {str(key): str(value) for key, value in (pypdf_reader.metadata or {}).items()}
    except Exception as exc:
        return {
            "success": False,
            "errors": [*errors, f"PDF parser failed: {type(exc).__name__}: {exc}"],
            "warnings": warnings,
        }
    if expected_pages is not None and pypdf_pages != expected_pages:
        errors.append(f"PDF has {pypdf_pages} pages, but Marp source has {expected_pages} slides.")
    if pypdf_pages < 1:
        errors.append("PDF has no pages.")

    page_rows: list[dict[str, Any]] = []
    all_sizes: list[float] = []
    internal_hits: list[dict[str, Any]] = []
    clipped_spans: list[dict[str, Any]] = []
    replacement_hits: list[dict[str, Any]] = []
    try:
        document = fitz.open(pdf_path)
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            page_rect = page.rect
            page_dict = page.get_text("dict")
            spans: list[dict[str, Any]] = []
            page_text_parts: list[str] = []
            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = str(span.get("text", ""))
                        if not text.strip():
                            continue
                        size = float(span.get("size", 0.0) or 0.0)
                        bbox = fitz.Rect(span.get("bbox", (0, 0, 0, 0)))
                        page_text_parts.append(text)
                        all_sizes.append(size)
                        row = {
                            "text": text[:180],
                            "font": str(span.get("font", "")),
                            "size_pt": round(size, 3),
                            "bbox": [round(value, 3) for value in bbox],
                        }
                        spans.append(row)
                        if not _page_rect_contains(page_rect, bbox):
                            clipped_spans.append({"page": page_index + 1, **row})
                        if "�" in text or "\ufffd" in text or "\u25a1" in text:
                            replacement_hits.append({"page": page_index + 1, **row})
            page_text = " ".join(page_text_parts)
            lower = page_text.lower()
            for term in INTERNAL_TERMS:
                if term.lower() in lower:
                    internal_hits.append({"page": page_index + 1, "term": term})
            page_rows.append(
                {
                    "page": page_index + 1,
                    "width_pt": round(page_rect.width, 3),
                    "height_pt": round(page_rect.height, 3),
                    "landscape": page_rect.width > page_rect.height,
                    "text_characters": len(page_text.strip()),
                    "span_count": len(spans),
                    "minimum_text_pt": min((row["size_pt"] for row in spans), default=None),
                }
            )
        document.close()
    except Exception as exc:
        errors.append(f"PyMuPDF inspection failed: {type(exc).__name__}: {exc}")

    if page_rows and any(not row["landscape"] for row in page_rows):
        errors.append("At least one PDF page is not landscape-oriented.")
    dimension_pairs = {(round(row["width_pt"], 1), round(row["height_pt"], 1)) for row in page_rows}
    if len(dimension_pairs) > 1:
        warnings.append("PDF pages do not all have the same dimensions.")
    minimum_size = min(all_sizes) if all_sizes else None
    if minimum_size is None:
        errors.append("PDF contains no extractable text spans.")
    elif minimum_size < error_min_text_pt:
        errors.append(
            f"PDF contains text as small as {minimum_size:.1f}pt; hard minimum is {error_min_text_pt:.1f}pt."
        )
    elif minimum_size < warning_min_text_pt:
        warnings.append(
            f"PDF contains text as small as {minimum_size:.1f}pt; verify readability below {warning_min_text_pt:.1f}pt."
        )
    if clipped_spans:
        errors.append(f"Detected {len(clipped_spans)} text span(s) outside PDF page bounds.")
    if replacement_hits:
        errors.append(f"Detected {len(replacement_hits)} possible missing-glyph/replacement span(s).")
    if internal_hits:
        warnings.append(
            "PDF student text contains internal production vocabulary: "
            + ", ".join(sorted({item['term'] for item in internal_hits}))
        )
    blank_pages = [row["page"] for row in page_rows if row["text_characters"] < 3]
    if blank_pages:
        warnings.append("PDF has pages with almost no text: " + ", ".join(map(str, blank_pages[:12])))
    return {
        "schema_version": 1,
        "pdf": str(pdf_path),
        "size_bytes": pdf_path.stat().st_size,
        "page_count": pypdf_pages,
        "expected_pages": expected_pages,
        "metadata": metadata,
        "pages": page_rows,
        "minimum_text_pt": minimum_size,
        "clipped_spans": clipped_spans[:80],
        "replacement_glyph_hits": replacement_hits[:80],
        "internal_term_hits": internal_hits,
        "errors": errors,
        "warnings": warnings,
        "success": not errors,
        "inspection_policy": "source/PDF structure and text only; no screenshots or raster review",
    }


def inspect_task_pdf(
    root: Path,
    slug: str,
    presentation_id: str,
    *,
    stage: str,
) -> dict[str, Any]:
    task = task_path(root, slug)
    if stage == "author":
        base = task / "workers" / "author-coordinator" / "drafts" / presentation_id
    elif stage == "release":
        base = task / "workers" / "release-coordinator" / "release-ready" / presentation_id
    else:
        raise MPresError("PDF inspection stage must be author or release.")
    source = base / "source"
    build = base / "build"
    deck = parse_deck(source / "presentation.md")
    policy = read_yaml(task / "EXECUTION-POLICY.yaml") or {}
    limits = policy.get("pdf_limits", {}) if isinstance(policy, dict) else {}
    report = inspect_pdf_file(
        build / f"{presentation_id}.pdf",
        expected_pages=len(deck.slides),
        warning_min_text_pt=float(limits.get("warning_min_text_pt", 12) or 12),
        error_min_text_pt=float(limits.get("error_min_text_pt", 8) or 8),
    )
    report["task_slug"] = slug
    report["presentation_id"] = presentation_id
    report["stage"] = stage
    report["source"] = relative_display(source / "presentation.md", root)
    report_path = build / f"pdf-inspection-{stage}.json"
    write_json_atomic(report_path, report)
    report["report_path"] = relative_display(report_path, root)
    return report
