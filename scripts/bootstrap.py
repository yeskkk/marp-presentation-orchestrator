#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import venv
from datetime import UTC, datetime
from pathlib import Path


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def venv_python(root: Path) -> Path:
    return root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(command: list[str], cwd: Path) -> None:
    print("+", " ".join(str(item) for item in command), flush=True)
    result = subprocess.run(command, cwd=cwd, check=False)
    if result.returncode:
        raise SystemExit(result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize Python and Marp CLI dependencies.")
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument("--no-dev", action="store_true")
    parser.add_argument("--with-figures", action="store_true")
    parser.add_argument("--skip-pip-upgrade", action="store_true")
    parser.add_argument("--skip-npm", action="store_true")
    parser.add_argument("--skip-browser-install", action="store_true")
    parser.add_argument("--no-doctor", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if sys.version_info < (3, 11):
        raise SystemExit("Python 3.11 or newer is required.")
    if shutil.which("node") is None or shutil.which("npm") is None:
        raise SystemExit("Node.js 18+ and npm are required.")
    environment = root / ".venv"
    if args.recreate and environment.exists():
        shutil.rmtree(environment)
    if not environment.exists():
        venv.EnvBuilder(with_pip=True, symlinks=os.name != "nt").create(environment)
    python = venv_python(root)
    if not args.skip_pip_upgrade:
        run([str(python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], root)
    extras: list[str] = []
    if not args.no_dev:
        extras.append("dev")
    if args.with_figures:
        extras.append("figures")
    target = "." + ("[" + ",".join(extras) + "]" if extras else "")
    run([str(python), "-m", "pip", "install", "--editable", target], root)
    if not args.skip_npm:
        npm_command = "npm.cmd" if os.name == "nt" else "npm"
        run([npm_command, "install", "--no-audit", "--no-fund", "--no-package-lock"], root)
    browser_override = os.environ.get("MPRES_CHROMIUM_EXECUTABLE", "").strip()
    browser_install_attempted = not args.skip_browser_install and not browser_override
    if browser_install_attempted:
        run([str(python), "-m", "playwright", "install", "chromium"], root)
    marker = {
        "completed_utc": utc_now(),
        "python": str(python),
        "with_figures": args.with_figures,
        "npm_install_skipped": args.skip_npm,
        "playwright_chromium_install_attempted": browser_install_attempted,
        "chromium_executable_override": browser_override or None,
    }
    (environment / ".mpres-bootstrap.json").write_text(
        json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if not args.no_doctor:
        run([str(python), "-m", "mpres", "doctor"], root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
