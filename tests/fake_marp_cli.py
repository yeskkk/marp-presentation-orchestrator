#!/usr/bin/env python3
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

VERSION = "__VERSION__"
OVERFLOW_HTML = __OVERFLOW__


def _slides(source: Path) -> list[list[str]]:
    text = source.read_text(encoding="utf-8")
    lines = text.splitlines()
    front_end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    body = lines[front_end + 1 :]
    chunks: list[list[str]] = []
    current: list[str] = []
    in_fence = False
    for line in body:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if line.strip() == "---" and not in_fence:
            chunks.append(current)
            current = []
        else:
            current.append(line)
    chunks.append(current)
    return chunks


def _write_html(output: Path, chunks: list[list[str]]) -> None:
    sections: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        chunk_text = "\n".join(chunk)
        match = re.search(r"<!--\s*slide-id:\s*([^\s]+)\s*-->", chunk_text)
        slide_id = match.group(1) if match else f"slide-{index}"
        visible = html.escape(re.sub(r"<!--.*?-->", "", chunk_text, flags=re.S))
        extra = '<div style="height:900px">overflow</div>' if OVERFLOW_HTML and index == 1 else ""
        sections.append(
            f'<section data-marpit-scope="1" id="{slide_id}" '
            'style="box-sizing:border-box;width:1280px;height:720px;overflow:hidden;padding:40px">'
            f'<pre style="white-space:pre-wrap">{visible}</pre>{extra}</section>'
        )
    output.write_text(
        '<!doctype html><html><head><meta charset="utf-8"><style>'
        'html,body{margin:0}.marpit>section{position:relative;display:block}'
        '</style></head><body><div class="marpit">'
        + "".join(sections)
        + "</div></body></html>",
        encoding="utf-8",
    )


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _write_pdf(output: Path, page_count: int) -> None:
    font_number = 3 + 2 * page_count
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            "<< /Type /Pages /Count %d /Kids [%s] >>"
            % (page_count, " ".join(f"{3 + 2 * index} 0 R" for index in range(page_count)))
        ).encode("ascii"),
        font_number: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for index in range(page_count):
        page_number = 3 + 2 * index
        content_number = page_number + 1
        objects[page_number] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 960 540] "
            f"/Resources << /Font << /F1 {font_number} 0 R >> >> "
            f"/Contents {content_number} 0 R >>"
        ).encode("ascii")
        title = _pdf_escape(f"Marp test slide {index + 1}")
        body = _pdf_escape("Readable mathematical presentation content.")
        stream = (
            f"BT /F1 28 Tf 72 450 Td ({title}) Tj 0 -50 Td /F1 22 Tf ({body}) Tj ET"
        ).encode("latin-1")
        objects[content_number] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"\nendstream"
        )
    maximum = max(objects)
    data = bytearray(b"%PDF-1.4\n%" + b"X" * 600 + b"\n")
    offsets = [0] * (maximum + 1)
    for number in range(1, maximum + 1):
        offsets[number] = len(data)
        data.extend(f"{number} 0 obj\n".encode("ascii"))
        data.extend(objects[number])
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {maximum + 1}\n".encode("ascii"))
    data.extend(b"0000000000 65535 f \n")
    for number in range(1, maximum + 1):
        data.extend(f"{offsets[number]:010d} 00000 n \n".encode("ascii"))
    data.extend(
        f"trailer\n<< /Size {maximum + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    output.write_bytes(bytes(data))


def main() -> int:
    if "--version" in sys.argv:
        print(VERSION)
        return 0
    args = sys.argv[1:]
    source = Path(args[0])
    output = Path(args[args.index("--output") + 1])
    chunks = _slides(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".html":
        _write_html(output, chunks)
    else:
        _write_pdf(output, len(chunks))
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
