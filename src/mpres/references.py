from __future__ import annotations

import mimetypes
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import fitz  # PyMuPDF
import pytesseract
import requests
from bs4 import BeautifulSoup
from PIL import Image
from pypdf import PdfReader

from mpres.logs import append_log
from mpres.tasks import require_gate
from mpres.util import (
    MPresError,
    executable,
    relative_display,
    task_path,
    utc_now,
    write_json_atomic,
)


def _safe_filename(name: str) -> str:
    name = unquote(name).strip().replace("\\", "_").replace("/", "_")
    name = re.sub(r"[^\w.()\[\] -]+", "_", name, flags=re.UNICODE)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:180] or "reference"


def _unique_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    counter = 2
    while True:
        next_path = directory / f"{stem}-{counter}{suffix}"
        if not next_path.exists():
            return next_path
        counter += 1


def _download(url: str, destination: Path, max_bytes: int = 300 * 1024 * 1024) -> tuple[str, str | None]:
    headers = {"User-Agent": "marp-presentation-orchestrator/0.1 reference-ingest"}
    with requests.get(url, headers=headers, stream=True, timeout=(20, 120), allow_redirects=True) as response:
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip() or None
        total = int(response.headers.get("content-length", "0") or 0)
        if total and total > max_bytes:
            raise MPresError(f"Reference is larger than the {max_bytes} byte download limit.")
        received = 0
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                received += len(chunk)
                if received > max_bytes:
                    raise MPresError(f"Reference exceeded the {max_bytes} byte download limit.")
                handle.write(chunk)
        return response.url, content_type


def _pdf_page_count(pdf_path: Path) -> int:
    try:
        return len(PdfReader(str(pdf_path)).pages)
    except Exception:
        try:
            return fitz.open(pdf_path).page_count
        except Exception:
            return 0


def _extract_pdf_pdftotext(pdf_path: Path, output_path: Path) -> dict[str, Any]:
    binary = executable("pdftotext")
    if not binary:
        return {"method": "pdftotext", "success": False, "error": "pdftotext not found"}
    process = subprocess.run(
        [binary, "-layout", "-enc", "UTF-8", str(pdf_path), str(output_path)],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    text = output_path.read_text(encoding="utf-8", errors="replace") if output_path.exists() else ""
    return {
        "method": "pdftotext",
        "success": process.returncode == 0 and bool(text.strip()),
        "returncode": process.returncode,
        "stderr": process.stderr[-4000:],
        "characters": len(text),
        "text": text,
    }


def _extract_pdf_pypdf(pdf_path: Path) -> dict[str, Any]:
    try:
        reader = PdfReader(str(pdf_path))
        pages: list[str] = []
        for index, page in enumerate(reader.pages, start=1):
            pages.append(f"\n\n===== PAGE {index} =====\n\n{page.extract_text() or ''}")
        text = "".join(pages)
        return {"method": "pypdf", "success": bool(text.strip()), "characters": len(text), "text": text}
    except Exception as exc:
        return {"method": "pypdf", "success": False, "error": f"{type(exc).__name__}: {exc}"}


def _preferred_ocr_languages() -> str:
    try:
        available = set(pytesseract.get_languages(config=""))
    except Exception:
        return "eng"
    preferred = [lang for lang in ("eng", "chi_sim", "chi_tra") if lang in available]
    if preferred:
        return "+".join(preferred)
    return next(iter(sorted(available)), "eng")


def _ocr_pdf(pdf_path: Path, max_pages: int | None) -> dict[str, Any]:
    if not executable("tesseract"):
        return {"method": "ocr", "success": False, "error": "tesseract not found"}
    languages = _preferred_ocr_languages()
    pages: list[str] = []
    try:
        document = fitz.open(pdf_path)
        page_count = document.page_count
        limit = page_count if max_pages is None else min(page_count, max_pages)
        matrix = fitz.Matrix(2.2, 2.2)
        for index in range(limit):
            page = document.load_page(index)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            mode = "RGB" if pixmap.n >= 3 else "L"
            image = Image.frombytes(mode, [pixmap.width, pixmap.height], pixmap.samples)
            text = pytesseract.image_to_string(image, lang=languages)
            pages.append(f"\n\n===== OCR PAGE {index + 1} =====\n\n{text}")
        text = "".join(pages)
        return {
            "method": "ocr",
            "success": bool(text.strip()),
            "characters": len(text),
            "pages_processed": limit,
            "pages_total": page_count,
            "languages": languages,
            "text": text,
        }
    except Exception as exc:
        return {"method": "ocr", "success": False, "error": f"{type(exc).__name__}: {exc}"}


def _is_sparse(text: str, pages: int) -> bool:
    nonspace = len(re.sub(r"\s+", "", text))
    threshold = max(500, max(pages, 1) * 90)
    return nonspace < threshold


def _extract_pdf(pdf_path: Path, text_path: Path, ocr_mode: str, max_pages: int | None) -> dict[str, Any]:
    pages = _pdf_page_count(pdf_path)
    attempts: list[dict[str, Any]] = []

    temp_path = text_path.with_suffix(".pdftotext.tmp")
    pdftotext_result = _extract_pdf_pdftotext(pdf_path, temp_path)
    attempts.append({k: v for k, v in pdftotext_result.items() if k != "text"})
    text = str(pdftotext_result.get("text", ""))
    method = "pdftotext"

    if not text.strip() or _is_sparse(text, pages):
        pypdf_result = _extract_pdf_pypdf(pdf_path)
        attempts.append({k: v for k, v in pypdf_result.items() if k != "text"})
        candidate = str(pypdf_result.get("text", ""))
        if len(re.sub(r"\s+", "", candidate)) > len(re.sub(r"\s+", "", text)):
            text = candidate
            method = "pypdf"

    sparse_before_ocr = _is_sparse(text, pages)
    should_ocr = ocr_mode == "always" or (ocr_mode == "auto" and sparse_before_ocr)
    if should_ocr:
        ocr_result = _ocr_pdf(pdf_path, max_pages)
        attempts.append({k: v for k, v in ocr_result.items() if k != "text"})
        candidate = str(ocr_result.get("text", ""))
        if candidate.strip():
            text = candidate
            method = "ocr"

    if temp_path.exists():
        temp_path.unlink()
    if not text.strip():
        raise MPresError("No useful text could be extracted from the PDF.")
    text_path.write_text(text, encoding="utf-8", newline="\n")
    return {
        "type": "pdf",
        "page_count": pages,
        "selected_method": method,
        "characters": len(text),
        "sparse_before_ocr": sparse_before_ocr,
        "sparse_final": _is_sparse(text, pages),
        "attempts": attempts,
    }


def _extract_html(source: Path, text_path: Path) -> dict[str, Any]:
    raw = source.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    text = soup.get_text("\n", strip=True)
    output = f"TITLE: {title}\n\n{text}" if title else text
    text_path.write_text(output, encoding="utf-8", newline="\n")
    return {"type": "html", "characters": len(output), "title": title}


def _extract_plain(source: Path, text_path: Path) -> dict[str, Any]:
    data = source.read_bytes()
    encoding = "utf-8"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("utf-16")
            encoding = "utf-16"
        except UnicodeDecodeError:
            text = data.decode("latin-1", errors="replace")
            encoding = "latin-1"
    text_path.write_text(text, encoding="utf-8", newline="\n")
    return {"type": "text", "characters": len(text), "source_encoding": encoding}


def ingest_reference(
    root: Path,
    slug: str,
    source_value: str,
    *,
    name: str | None,
    ocr_mode: str,
    max_pages: int | None,
) -> dict[str, Any]:
    require_gate(root, slug)
    if ocr_mode not in {"auto", "always", "never"}:
        raise MPresError("OCR mode must be auto, always, or never.")
    task = task_path(root, slug)
    originals = task / "downloads" / "originals"
    text_dir = task / "downloads" / "text"
    metadata_dir = task / "downloads" / "metadata"
    originals.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)

    parsed = urlparse(source_value)
    is_url = parsed.scheme.lower() in {"http", "https"}
    resolved_url: str | None = None
    content_type: str | None = None
    if is_url:
        inferred = Path(parsed.path).name or "downloaded-reference"
        filename = _safe_filename(name or inferred)
        if not Path(filename).suffix:
            filename += ".bin"
        destination = _unique_path(originals, filename)
        resolved_url, content_type = _download(source_value, destination)
        if destination.suffix == ".bin" and content_type:
            extension = mimetypes.guess_extension(content_type) or ""
            if extension:
                renamed = _unique_path(originals, destination.stem + extension)
                destination.rename(renamed)
                destination = renamed
    else:
        local = Path(source_value).expanduser().resolve()
        if not local.is_file():
            raise MPresError(f"Reference file does not exist: {local}")
        filename = _safe_filename(name or local.name)
        if not Path(filename).suffix and local.suffix:
            filename += local.suffix
        destination = _unique_path(originals, filename)
        shutil.copy2(local, destination)
        content_type = mimetypes.guess_type(destination.name)[0]

    lower_suffix = destination.suffix.lower()
    text_path = _unique_path(text_dir, destination.stem + ".txt")
    if lower_suffix == ".pdf" or content_type == "application/pdf":
        extraction = _extract_pdf(destination, text_path, ocr_mode, max_pages)
    elif lower_suffix in {".html", ".htm"} or content_type == "text/html":
        extraction = _extract_html(destination, text_path)
    elif lower_suffix in {".txt", ".md", ".tex", ".bib", ".rst", ".csv", ".json", ".xml"} or (
        content_type and content_type.startswith("text/")
    ):
        extraction = _extract_plain(destination, text_path)
    else:
        raise MPresError(
            f"Unsupported reference type {destination.suffix or content_type!r}. Convert it to PDF, HTML, or text first."
        )

    metadata = {
        "ingested_utc": utc_now(),
        "task_slug": slug,
        "source_input": source_value,
        "resolved_url": resolved_url,
        "content_type": content_type,
        "original_path": relative_display(destination, root),
        "original_size_bytes": destination.stat().st_size,
        "text_path": relative_display(text_path, root),
        "text_size_bytes": text_path.stat().st_size,
        "extraction": extraction,
        "warning": (
            "OCR/extraction text is a search aid. Check formulas, diagrams, and quotations against the original."
        ),
    }
    metadata_path = _unique_path(metadata_dir, destination.stem + ".json")
    write_json_atomic(metadata_path, metadata)

    index = task / "downloads" / "INDEX.md"
    with index.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            f"\n## {destination.name}\n\n"
            f"- Ingested UTC: {metadata['ingested_utc']}\n"
            f"- Original: `{metadata['original_path']}`\n"
            f"- Extracted text: `{metadata['text_path']}`\n"
            f"- Method: `{extraction.get('selected_method', extraction.get('type'))}`\n"
            f"- Original size: `{metadata['original_size_bytes']}` bytes\n"
        )
    append_log(
        root,
        slug,
        actor="planner",
        kind="progress",
        message=f"Ingested shared reference {destination.name}.",
        data={
            "original": metadata["original_path"],
            "text": metadata["text_path"],
            "method": extraction.get("selected_method", extraction.get("type")),
        },
    )
    return metadata
