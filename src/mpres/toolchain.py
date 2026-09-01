from __future__ import annotations

import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import fitz

from mpres.html_layout import inspect_marp_html_layout
from mpres.util import MPresError, executable, local_marp_binary, parse_utc, read_yaml, run_command, utc_now, write_yaml_atomic


def load_toolchain_lock(root: Path) -> dict[str, Any]:
    value = read_yaml(root / "TOOLCHAIN-LOCK.yaml")
    if not isinstance(value, dict):
        raise MPresError("TOOLCHAIN-LOCK.yaml is missing or malformed.")
    return value


def _marp_command(root: Path) -> list[str]:
    binary = local_marp_binary(root)
    if binary is None:
        raise MPresError("Pinned local Marp CLI is not installed. Run npm install.")
    if binary.suffix.lower() == ".js":
        return [executable("node") or "node", str(binary)]
    return [str(binary)]


def installed_marp_version(root: Path) -> dict[str, Any]:
    """Read the local Marp CLI version and compare it with the repository lock."""

    lock = load_toolchain_lock(root)
    expected = str(((lock.get("marp") or {}).get("version") or "")).strip()
    install_policy = str(((lock.get("marp") or {}).get("install_policy") or "")).strip()
    if install_policy != "exact_pinned_version" or not expected:
        raise MPresError("TOOLCHAIN-LOCK.yaml must define an exact pinned Marp version.")
    process = run_command([*_marp_command(root), "--version"], cwd=root, timeout=30)
    output = (process.stdout or process.stderr).strip().splitlines()
    actual_line = output[0] if output else ""
    match = re.search(r"(\d+\.\d+\.\d+)", actual_line)
    actual = match.group(1) if match else actual_line
    return {
        "expected": expected,
        "actual": actual,
        "returncode": process.returncode,
        "matches": process.returncode == 0 and actual == expected,
    }


def require_pinned_marp(root: Path) -> dict[str, Any]:
    result = installed_marp_version(root)
    if not result["matches"]:
        raise MPresError(
            f"Pinned Marp version mismatch: expected {result['expected']}, "
            f"found {result['actual'] or 'unknown'}. Run npm install before continuing."
        )
    return result


def smoke_toolchain(root: Path, *, timeout: int = 120) -> dict[str, Any]:
    version = installed_marp_version(root)
    expected = str(version["expected"])
    actual = str(version["actual"])
    errors: list[str] = []
    if version["returncode"] != 0:
        errors.append("Marp --version failed.")
    if not version["matches"]:
        errors.append(f"Pinned Marp version mismatch: expected {expected}, found {actual or 'unknown'}.")

    with tempfile.TemporaryDirectory(prefix="mpres-toolchain-smoke-") as raw:
        temp = Path(raw)
        source = temp / "source"
        source.mkdir()
        (source / "theme.css").write_text(
            "/* @theme mathist-academic */\nsection{font-family:Arial,sans-serif;}\n",
            encoding="utf-8",
        )
        (source / "presentation.md").write_text(
            "---\nmarp: true\ntheme: mathist-academic\npaginate: true\nsize: 16:9\nmath: mathjax\n---\n"
            "<!-- slide-id: smoke-01 -->\n# Smoke test\n\nInline math $x^2+1$.\n\n---\n"
            "<!-- slide-id: smoke-02 -->\n## Second slide\n\n$$A=\\begin{pmatrix}1&0\\\\0&1\\end{pmatrix}$$\n\n---\n"
            "<!-- slide-id: smoke-03 -->\n## Meeting schema\n\nGlobal meeting 3; deck-local ordinal 1.\n",
            encoding="utf-8",
        )
        policy = {
            "marp": {"browser": "auto"},
            "inspection": {"screenshots": "forbidden"},
        }
        html = inspect_marp_html_layout(root, source, policy=policy, timeout=timeout)
        if not html.get("success"):
            errors.extend(str(x) for x in html.get("errors", []))
        pdf = temp / "smoke.pdf"
        command = [
            *_marp_command(root),
            str(source / "presentation.md"),
            "--pdf",
            "--allow-local-files",
            "--html",
            "--theme-set",
            str(source / "theme.css"),
            "--output",
            str(pdf),
        ]
        process = run_command(command, cwd=source, timeout=timeout)
        pages = 0
        if process.returncode != 0 or not pdf.is_file():
            errors.append("Pinned Marp could not produce the three-slide smoke PDF.")
        else:
            document = fitz.open(pdf)
            pages = document.page_count
            document.close()
            if pages != 3:
                errors.append(f"Smoke PDF expected 3 pages, found {pages}.")

    report = {
        "schema_version": 1,
        "completed_utc": utc_now(),
        "expected_marp_version": expected,
        "actual_marp_version": actual,
        "html_slide_count": html.get("slide_count", 0),
        "pdf_page_count": pages,
        "meeting_number_fields": ["global_meeting_number", "deck_local_ordinal"],
        "errors": errors,
        "success": not errors,
    }
    output_path = root / ".mpres" / "toolchain-smoke.yaml"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml_atomic(output_path, report)
    report["report_path"] = str(output_path)
    return report


def require_recent_smoke(root: Path) -> dict[str, Any]:
    report = read_yaml(root / ".mpres" / "toolchain-smoke.yaml")
    if not isinstance(report, dict) or report.get("success") is not True:
        raise MPresError("Run `mpres toolchain smoke` successfully before production initialization.")
    lock = load_toolchain_lock(root)
    expected = str(((lock.get("marp") or {}).get("version") or ""))
    if str(report.get("expected_marp_version") or "") != expected:
        raise MPresError("Toolchain smoke report predates the current TOOLCHAIN-LOCK.yaml.")
    if str(report.get("actual_marp_version") or "") != expected:
        raise MPresError("Toolchain smoke did not run with the currently pinned Marp version.")
    if int(report.get("html_slide_count", 0) or 0) != 3 or int(report.get("pdf_page_count", 0) or 0) != 3:
        raise MPresError("Toolchain smoke must verify exactly three HTML slides and three PDF pages.")
    if report.get("meeting_number_fields") != ["global_meeting_number", "deck_local_ordinal"]:
        raise MPresError("Toolchain smoke lacks the required global/deck-local meeting-number schema.")
    completed = parse_utc(str(report.get("completed_utc") or ""))
    if completed is None:
        raise MPresError("Toolchain smoke report lacks a valid completion timestamp.")
    max_age_hours = float(((lock.get("inspection") or {}).get("smoke_max_age_hours") or 24))
    age_hours = (datetime.now(UTC) - completed).total_seconds() / 3600
    if age_hours < -0.1 or age_hours > max_age_hours:
        raise MPresError(
            f"Toolchain smoke report is not recent enough ({age_hours:.1f} h; limit {max_age_hours:g} h)."
        )
    require_pinned_marp(root)
    return report
