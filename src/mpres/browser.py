from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path
from typing import Any

from mpres.util import MPresError


def _browser_override() -> Path | None:
    raw = os.environ.get("MPRES_CHROMIUM_EXECUTABLE", "").strip()
    return Path(raw).expanduser().absolute() if raw else None


def _system_browser() -> Path | None:
    for name in (
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
        "microsoft-edge",
        "msedge",
    ):
        value = shutil.which(name)
        if value:
            return Path(value).absolute()
    return None


def browser_launch_options(playwright: Any) -> tuple[dict[str, Any], Path, str]:
    override = _browser_override()
    managed = Path(playwright.chromium.executable_path)
    system = _system_browser()
    if override:
        executable = override
        source = "MPRES_CHROMIUM_EXECUTABLE"
    elif managed.is_file():
        executable = managed
        source = "playwright-managed"
    elif system:
        executable = system
        source = "system"
    else:
        raise MPresError(
            "No Chromium-family browser is available for temporary Marp HTML inspection. "
            "Run `python -m playwright install chromium` or set MPRES_CHROMIUM_EXECUTABLE."
        )
    if not executable.is_file():
        raise MPresError(f"Configured Chromium executable does not exist: {executable}")
    options: dict[str, Any] = {"headless": True, "executable_path": str(executable)}
    raw_args = os.environ.get("MPRES_CHROMIUM_ARGS", "").strip()
    if raw_args:
        options["args"] = shlex.split(raw_args, posix=os.name != "nt")
    return options, executable, source


def browser_probe() -> dict[str, Any]:
    result: dict[str, Any] = {
        "available": False,
        "executable": None,
        "source": None,
        "browser_version": None,
        "error": None,
    }
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - environment-specific
        result["error"] = f"Playwright import failed: {type(exc).__name__}: {exc}"
        return result
    try:
        with sync_playwright() as playwright:
            options, executable, source = browser_launch_options(playwright)
            result["executable"] = str(executable)
            result["source"] = source
            browser = playwright.chromium.launch(**options)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.set_content(
                    "<!doctype html><style>section{width:1280px;height:720px}</style>"
                    "<section>mpres layout probe</section>",
                    wait_until="load",
                )
                dimensions = page.locator("section").evaluate(
                    "el => ({clientWidth:el.clientWidth,clientHeight:el.clientHeight})"
                )
                if dimensions != {"clientWidth": 1280, "clientHeight": 720}:
                    raise RuntimeError(f"Unexpected browser layout probe result: {dimensions}")
                result["browser_version"] = browser.version
            finally:
                browser.close()
            result["available"] = True
    except Exception as exc:  # pragma: no cover - environment-specific
        result["error"] = f"Chromium layout probe failed: {type(exc).__name__}: {exc}"
    return result
