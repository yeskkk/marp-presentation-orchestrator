from __future__ import annotations

import importlib.metadata
import json
import re
import os
import platform
import sys
import tempfile
from pathlib import Path
from typing import Any

import fitz

from mpres.util import executable, local_marp_binary, run_command, virtualenv_python


def _binary_check(name: str, args: list[str] | None = None) -> dict[str, Any]:
    path = executable(name)
    result: dict[str, Any] = {"name": name, "found": bool(path), "path": path, "version": None}
    if path and args is not None:
        process = run_command([path, *args], timeout=30)
        lines = (process.stdout or process.stderr).strip().splitlines()
        result["version"] = lines[0] if lines else None
        result["returncode"] = process.returncode
    return result


def _marp_check(root: Path) -> dict[str, Any]:
    binary = local_marp_binary(root)
    if binary is None:
        return {"found": False, "path": None, "version": None, "returncode": None}
    command = [str(binary), "--version"]
    if binary.suffix.lower() == ".js":
        node = executable("node")
        command = [node or "node", str(binary), "--version"]
    process = run_command(command, timeout=30)
    lines = (process.stdout or process.stderr).strip().splitlines()
    return {
        "found": True,
        "path": str(binary),
        "version": lines[0] if lines else None,
        "returncode": process.returncode,
    }


def _marp_pdf_probe(root: Path, marp: dict[str, Any]) -> dict[str, Any]:
    if not marp.get("found") or marp.get("returncode") != 0:
        return {"ok": False, "error": "Marp CLI is unavailable."}
    binary = Path(str(marp["path"]))
    with tempfile.TemporaryDirectory(prefix="mpres-doctor-") as raw:
        temp = Path(raw)
        source = temp / "probe.md"
        theme = temp / "theme.css"
        pdf = temp / "probe.pdf"
        source.write_text(
            "---\nmarp: true\ntheme: probe\npaginate: true\nsize: 16:9\nmath: mathjax\n---\n"
            "<!-- _class: core -->\n<!-- slide-id: probe-1 -->\n# Marp PDF probe\n",
            encoding="utf-8",
        )
        theme.write_text("/* @theme probe */\nsection{font-family:Arial,sans-serif;}\n", encoding="utf-8")
        command = [str(binary)]
        if binary.suffix.lower() == ".js":
            command = [executable("node") or "node", str(binary)]
        command.extend([
            str(source), "--pdf", "--allow-local-files", "--html",
            "--theme-set", str(theme), "--output", str(pdf),
        ])
        process = run_command(command, cwd=temp, timeout=120)
        if process.returncode or not pdf.is_file():
            return {
                "ok": False,
                "command": command,
                "returncode": process.returncode,
                "stderr": process.stderr[-4000:],
                "error": "Marp could not produce the probe PDF.",
            }
        try:
            document = fitz.open(pdf)
            pages = document.page_count
            document.close()
        except Exception as exc:
            return {"ok": False, "error": f"Probe PDF cannot be parsed: {exc}"}
        return {
            "ok": pages == 1,
            "command": command,
            "returncode": process.returncode,
            "pages": pages,
            "size_bytes": pdf.stat().st_size,
            "error": None if pages == 1 else f"Expected 1 probe page, got {pages}.",
        }


def doctor_report(root: Path, *, run_pdf_probe: bool = True) -> dict[str, Any]:
    packages: dict[str, Any] = {}
    for package in [
        "marp-presentation-orchestrator",
        "beautifulsoup4",
        "Pillow",
        "PyMuPDF",
        "pypdf",
        "pytesseract",
        "PyYAML",
        "requests",
        "python-slugify",
        "matplotlib",
        "numpy",
        "sympy",
    ]:
        try:
            packages[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            packages[package] = None
    binaries = {
        "codex": _binary_check("codex", ["--version"]),
        "node": _binary_check("node", ["--version"]),
        "npm": _binary_check("npm", ["--version"]),
        "pdftotext": _binary_check("pdftotext", ["-v"]),
        "tesseract": _binary_check("tesseract", ["--version"]),
        "git": _binary_check("git", ["--version"]),
    }
    marp = _marp_check(root)
    probe = _marp_pdf_probe(root, marp) if run_pdf_probe else {"ok": None, "skipped": True}
    node_version_text = str(binaries["node"].get("version") or "")
    node_match = re.search(r"(?:^|v)(\d+)", node_version_text)
    node_ok = bool(node_match and int(node_match.group(1)) >= 18)
    expected_marp = json.loads((root / "package.json").read_text(encoding="utf-8"))["devDependencies"]["@marp-team/marp-cli"]
    marp_version_text = str(marp.get("version") or "").strip().lstrip("v")
    marp_version_ok = marp_version_text.startswith(str(expected_marp))
    required = {
        "python>=3.11": sys.version_info >= (3, 11),
        "codex": binaries["codex"]["found"],
        "node>=18": node_ok,
        "npm": binaries["npm"]["found"],
        "marp": marp.get("found") and marp.get("returncode") == 0 and marp_version_ok,
        "marp_pdf": probe.get("ok") is True if run_pdf_probe else True,
        "pdftotext": binaries["pdftotext"]["found"],
        "tesseract_optional": binaries["tesseract"]["found"],
    }
    blockers = [
        key for key in ("python>=3.11", "codex", "node>=18", "npm", "marp", "marp_pdf", "pdftotext")
        if not required[key]
    ]
    warnings: list[str] = []
    if not binaries["tesseract"]["found"]:
        warnings.append("Tesseract is absent; scanned references cannot use OCR fallback.")
    if virtualenv_python(root) is None:
        warnings.append("Project .venv is absent; run scripts/bootstrap.py.")
    if packages["matplotlib"] is None:
        warnings.append("Optional Python figure support is not installed; this is normal while figures remain disabled.")
    if probe.get("error"):
        warnings.append(str(probe["error"]))
    return {
        "ok": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "root": str(root),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": {
            "version": sys.version.split()[0],
            "executable": sys.executable,
            "in_project_venv": Path(sys.prefix).resolve() == (root / ".venv").resolve(),
        },
        "packages": packages,
        "binaries": binaries,
        "marp": {**marp, "expected_version": expected_marp, "version_ok": marp_version_ok},
        "pdf_probe": probe,
    }
