# Validation record — v0.3.0

Validation date: 2026-08-30 UTC.

## Policy represented by this release

This release implements the confirmed branch policy:

- Marp CLI is unpinned; `package.json` requests `latest`, `.npmrc` disables lockfile creation, and `package-lock.json` is rejected.
- Every worker role uses `gpt-5.6-sol` with reasoning effort `high` by default.
- There is one frozen full-deck review in five isolated channels.
- After aggregation, the author responds to every finding, revises, completes the modification checklist, reruns deterministic checks, and proceeds directly to release. Reviewers do not recheck the revision and findings do not carry resolution state.
- The planner personally writes and approves every role assignment and every authoring-stage assignment.
- Course content units require two or three diagnostic MCQ prompt/answer pairs; academic reports are exempt.
- Workers may read only extracted text under `downloads/text/`; original PDF paths and restricted ingestion metadata are blocked from assignments, stage artifacts and review bundles.
- Formal slide inspection uses source and PDF structure only. Screenshots, page raster/contact sheets and model vision are forbidden.
- Only the top-level task `TASK.md` may use a confirmation digest.

## Automated validation completed

The following checks passed in the build tree:

```bash
rm -rf .pytest_cache
find . -type d -name __pycache__ -prune -exec rm -rf {} +
PYTHONPATH=src pytest -q
python -m compileall -q src scripts tests
PYTHONPATH=src python scripts/validate_project.py --skip-tests
bash -n start.sh start-safe.sh
PYTHONPATH=src python -m mpres --help
```

Current regression result: **20 passed**.

The suite covers, among other rules:

1. the TASK-only digest gate and reconfirmation sequence for material policy changes;
2. one full review and five isolated channels;
3. no reviewer verification or finding-resolution gate after author revision;
4. direct release after complete author responses, checklist, self-check and fresh PDF build;
5. planner-written assignment contracts, including every authoring stage;
6. six-stage course authoring and compact report authoring;
7. exactly two or three course MCQs per content unit and report exemption;
8. prompt/answer adjacency, core/support roles and option audits;
9. unpinned arbitrary Marp CLI versions and PDF-only rendering through a controlled executable;
10. rejection of persistent HTML, non-TASK digests, remote images and restricted reference paths;
11. restricted original-file ingestion and worker-visible extracted-text indexing;
12. verified GeoGebra material links and rejection of embedding or unverified materials;
13. author/reviewer thread independence and durable handoff requirements;
14. exact token accounting without estimates; and
15. event-aware planner supervision after twenty minutes or a delivery event.

`validate_project.py` additionally parses all project TOML files, JSON files and JSON schemas; fills documented placeholders and parses every YAML policy/registry template with duplicate-key detection; checks POSIX launcher syntax; and rejects `package-lock.json`.

## External environment observed

Present in the build environment:

- Python 3.13.5;
- Node.js 22.16.0;
- npm 10.9.2;
- Chromium 144.0.7559.96;
- `pdftotext` 25.06.0;
- Tesseract 5.5.0;
- Git 2.47.3.

Unavailable:

- Codex CLI;
- locally installed `@marp-team/marp-cli`;
- Ruff.

A real npm installation was attempted with:

```bash
npm install --no-audit --no-fund --no-package-lock
```

The registry request failed because DNS resolution for `registry.npmjs.org` returned `EAI_AGAIN`. Consequently this build does **not** claim a real Marp CLI → PDF smoke test or a real Codex multi-agent run. The regression suite uses a controlled Marp executable that accepts arbitrary version output and writes real, parseable PDFs, thereby testing command construction, frozen-source handling, PDF-only output, source lint, PDF inspection, review handoff, author revision and release state transitions.

The target machine must still run:

```bash
python scripts/bootstrap.py
.venv/bin/mpres doctor --strict
```

and pass the doctor's real one-page Marp PDF probe before production use.

Ruff remains a development dependency and should be run after bootstrap:

```bash
.venv/bin/ruff check src tests scripts
```

## Packaging policy

The source archive excludes `.venv`, `node_modules`, npm caches, pytest caches, `__pycache__`, `.pyc`, generated tasks and build products. In accordance with the project policy, no archive checksum or source-manifest digest is generated; only a future task's top-level `TASK.md` may use a confirmation digest.
