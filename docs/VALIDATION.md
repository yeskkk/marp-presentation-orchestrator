# Validation record — v0.4.1

Validation date: 2026-08-31 UTC.

## Policy represented by this release

This release implements the following confirmed policy:

- durable production remains **Marp Markdown → PDF**; HTML is never a review or delivery artifact;
- the author and release pipelines may generate disposable Marp HTML solely for deterministic overflow inspection, and delete it before returning;
- author-side temporary-HTML inspection is a blocking submission gate; specialist reviewers do not reproduce or adjudicate mechanical overflow, clipping, browser, or PDF-bound checks;
- the root `MODEL-POLICY.yaml` is the single source of truth: planner `gpt-5.6-sol/max`, workers `gpt-5.6-sol/high`;
- course decks are organized by sequentially numbered class meetings, not by textbook chapter divisions;
- a nominal 40-minute meeting may deliberately contain about 60 minutes of prepared material: the nominal-duration core path has a natural stopping point, while the optional tail is mainly explanatory worked examples and need not be presented;
- the time ratio is a planning heuristic and warning source, not a hard completion quota;
- verified GeoGebra material links may be reused across meetings; duplicate URLs are not an error;
- there is one frozen full-deck review in five isolated channels; after the author completes the modification workflow, the deck proceeds directly to mechanical release without reviewer re-verification or finding-resolution status;
- original reference PDFs remain unavailable to workers; workers use extracted text only;
- screenshots, PDF contact sheets, page raster review, and model vision remain forbidden;
- Marp CLI remains unpinned and `package-lock.json` remains forbidden;
- only the top-level task `TASK.md` may use a user-confirmation digest.

## Automated validation completed

The following checks passed in the working tree:

```bash
export TERM=xterm
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src pytest -q
python -m compileall -q src scripts tests
PYTHONPATH=src python scripts/validate_project.py
bash -n start.sh start-safe.sh
PYTHONPATH=src python -m mpres --help
PYTHONPATH=src python -m mpres inspect html-layout --help
PYTHONPATH=src python -m mpres render --help
```

Current regression result: **24 passed**.

The suite covers, among other rules:

1. the TASK-only confirmation-digest gate and reconfirmation sequence for material policy changes;
2. one full review in five isolated channels, followed by author-owned revision and direct release;
3. no reviewer verification or finding-resolution gate after author revision;
4. planner-written assignment contracts and role/thread independence;
5. course authoring stages and the academic-report profile;
6. two or three diagnostic MCQ prompt/answer pairs per course meeting and report exemption;
7. numbered course-meeting organization and visible `第 N 节课` boundaries;
8. advisory lesson-time plans, including the 40-minute → approximately 60-minute preparation example, an explicit core stopping point, and an optional worked-example tail;
9. author-side disposable Marp HTML generation, per-slide `scrollWidth`/`scrollHeight` and bounds inspection, failure before PDF creation when overflow is present, and deletion of temporary HTML;
10. successful author mechanical evidence being excluded from specialist-review bundles;
11. release-side repetition of the mechanical HTML overflow gate without retaining HTML;
12. PDF-only durable output, PDF structure/text inspection, and rejection of persistent HTML;
13. source lint, interaction manifests, MCQ audits, and bare TeX control-word blocking;
14. extracted-text-only reference access and rejection of original-PDF paths in worker-visible material;
15. verified GeoGebra material links, rejection of embeds and unverified resources, and permitted reuse of the same URL across meetings;
16. exact token accounting without estimation; and
17. event-aware planner supervision after twenty minutes or a delivery event.

`validate_project.py` additionally:

- parses all project TOML files;
- parses all JSON files and JSON schemas;
- fills documented placeholders and parses all YAML policies and registries with duplicate-key detection;
- checks POSIX launcher syntax;
- rejects `package-lock.json`;
- runs the regression suite with third-party pytest plugin autoload disabled for deterministic completion.

## Real browser validation

The build environment contained Playwright 1.57.0 and system Chromium 144.0.7559.96. Two real-browser checks passed:

1. `mpres.browser.browser_probe()` launched Chromium and verified a 1280×720 layout element;
2. a controlled Marp-compatible executable generated disposable HTML, after which the production Playwright inspector found one slide, zero overflow, and no retained temporary HTML.

The inspector uses the actual rendered Marpit section dimensions rather than hard-coding a universal deck size. It locates:

```css
section[data-marpit-scope], .marpit > section
```

and compares each slide's `scrollWidth`/`scrollHeight` with its `clientWidth`/`clientHeight`, while also recording direct-child elements outside slide bounds, duplicate slide IDs, page errors, failed local requests, and blocked external requests. No screenshots or model vision are used.

## External environment observed

Present in the build environment:

- Python 3.13.5;
- pytest 9.0.2;
- Playwright 1.57.0;
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

Consequently this build does **not** claim a real Codex multi-agent run or a real installed-Marp-CLI → PDF smoke test. The regression suite uses a controlled Marp executable that accepts arbitrary version output and writes real, parseable PDFs; the disposable-HTML portion was additionally exercised against real Chromium as described above.

The target machine must still run:

```bash
python scripts/bootstrap.py
.venv/bin/mpres doctor --strict
```

and pass the doctor's real Marp PDF probe and Chromium layout probe before production use.

Ruff remains a development dependency and should be run after bootstrap:

```bash
.venv/bin/ruff check src tests scripts
```

## Packaging policy

The source archive excludes `.venv`, `node_modules`, browser caches, pytest/Ruff caches, `__pycache__`, `.pyc`, generated tasks, generated HTML/PDF, and build products. In accordance with project policy, no archive checksum or source-manifest digest is generated; only a future task's top-level `TASK.md` may use a confirmation digest.
