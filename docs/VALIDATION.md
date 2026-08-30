# Validation record — v0.2.0

Validation date: 2026-08-30 UTC.

## Scope of this release

This release adds optional, bounded GeoGebra resource discovery to the Marp authoring workflow.
The search is restricted to GeoGebra's own site. A selected material must be a public
`https://www.geogebra.org/m/<resource-id>` URL and may appear in a deck only as an ordinary,
descriptive Markdown hyperlink. Applets, iframes, scripts, preview images, screenshots, QR codes,
downloaded copies, and mirrored resources remain forbidden. The deck must remain complete when the
link is not opened.

Each content unit now records its decision in `GEOGEBRA-RESOURCES.yaml`:

- `not_applicable` when dynamic GeoGebra exploration is not instructionally relevant;
- `searched_no_suitable_resource` after a relevant, bounded site-only search finds nothing worth
  citing;
- `found_selected` when one to three suitable public materials are selected and linked.

The author coordinator validates every unit record, consolidates the presentation-level registry,
and cross-checks selected URLs and link labels against canonical `presentation.md`.

## Automated checks completed

The following commands completed successfully in the build environment:

```bash
python -m compileall -q src scripts tests
PYTHONPATH=src pytest -q
bash -n start.sh start-safe.sh
PYTHONPATH=src python -m mpres --help
PYTHONPATH=src python -m mpres geogebra validate --help
PYTHONPATH=src python -m mpres render --help
```

Test result: **24 passed**.

The test suite covers, among other workflow rules:

1. TASK.md confirmation and the no-non-TASK-hash policy;
2. role-based parallel production without `worker1`/`worker2` names;
3. Marp source lint and PDF-only rendering through a controlled Marp test executable;
4. three mandatory review rounds, five channels, terminal closure, and delivery pauses;
5. disabled-by-default Python figure generation and asset-decision enforcement;
6. valid GeoGebra material links and unit-to-presentation aggregation;
7. rejection of third-party domains, generic GeoGebra home pages, bare URLs, HTML anchors,
   autolinks, image links, iframe/applet embedding, unregistered links, malformed resource records,
   invalid timestamps, excessive search queries, and missing `site:geogebra.org` restrictions.

All project TOML files parsed successfully. JSON files and JSON schemas parsed successfully. YAML
policy and registry templates parsed successfully after substituting their documented placeholders;
the raw deck-manifest template intentionally contains a multiline insertion placeholder and is
validated through generated-task tests.

## External environment observed

Present:

- Python 3.13.5;
- Node.js 22.16.0;
- npm 10.9.2;
- Chromium 144.0.7559.96;
- `pdftotext` 25.06.0;
- Tesseract 5.5.0;
- Git 2.47.3.

Unavailable in this build environment:

- Codex CLI;
- locally installed `@marp-team/marp-cli`;
- Ruff.

The project pins `@marp-team/marp-cli` to version 4.5.0 in `package.json`. An npm registry probe was
attempted, but DNS resolution for `registry.npmjs.org` failed with `EAI_AGAIN`. Consequently, this
build does **not** claim a real Marp CLI → PDF smoke test. The controlled Marp test executable writes
real, parseable PDF files and exercises source freezing, PDF-only output, report generation, PDF
inspection, review handoff, and release logic. The target machine must still run:

```bash
python scripts/bootstrap.py
.venv/bin/mpres doctor --strict
```

and complete the doctor's real one-page Marp PDF probe before production use.

Ruff remains a development dependency and should be run after bootstrap:

```bash
.venv/bin/ruff check src tests scripts
```

## Packaging policy

The source archive excludes `.venv`, `node_modules`, npm caches, pytest caches, `__pycache__`, `.pyc`
files, generated tasks, and build products. In accordance with the project rule, no package checksum
or source manifest hash is generated; only a future task's top-level `TASK.md` may use a confirmation
digest.
