# Validation record — v0.5.0

Validation date: 2026-08-31 UTC.

## Policy represented by this release

This release keeps the confirmed v0.4.1 policies and adds the remaining lightweight improvements requested for v0.5.0:

- one persistent Python logging daemon serializes every role's requests into one task-level `logs/project.jsonl`; callers do not manage or observe concurrency locks;
- there is no crash-recovery subsystem, orchestration attempt journal, workflow-engine freeze, or token-attempt accounting extension;
- `MODEL-POLICY.yaml` is the global runtime source of truth: planner `gpt-5.6-sol/max`, workers `gpt-5.6-sol/high`;
- one planner-approved lesson assignment and one lesson-author thread run all internal authoring stages in sequence; stage artifacts and checkpoints remain durable, but stages do not create new assignments or workers;
- deterministic launch plans validate assignments, runtime policy, thread capacity and reusable handles without creating an orchestration journal;
- one full-deck five-channel review remains authoritative; author revision is not re-reviewed before release;
- reviewer handoffs are validated as one atomic batch before the shared finding registry changes; pre-aggregation resubmission may correct only location, evidence path and reviewer note;
- findings are routed mechanically to lesson authors or the author coordinator from structured slide/source/unit locations;
- course-level terminology, semantic objects, cross-deck handoffs and presentation continuity are validated;
- mathematical typesetting inspection has only source and disposable-HTML renderer layers; no `MATH-PDF-EVIDENCE` artifact exists;
- slide-density review records one principal teaching move, substantial blocks and any split rationale;
- already delivered presentations may enter numbered targeted-patch or full-corrective-review maintenance cycles without silently overwriting the prior release;
- author-side disposable Marp HTML overflow inspection remains a blocking submission gate; reviewers do not repeat mechanical layout inspection;
- final durable output remains Marp PDF only; screenshots, page raster review, model vision and worker access to original reference PDFs remain forbidden;
- Marp CLI remains unpinned and `package-lock.json` remains forbidden;
- only the task's top-level `TASK.md` may use a user-confirmation digest.

## Automated regression

The complete regression suite was run with third-party pytest plugin autoload disabled:

```bash
export TERM=xterm
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export PYTHONPATH=src
python -m pytest -vv
```

Result:

```text
33 passed in 47.57s
```

The tests cover, among other things:

1. the persistent project-level logger daemon under 120 concurrent clients, unique daemon sequencing, and absence of per-role log files;
2. global planner/worker model policy and reserved thread capacity;
3. one planner-approved lesson assignment and one same-thread stage sequence, with no stage-specific assignment files;
4. current launch plans without attempt-journal directories;
5. one isolated full review in five channels, narrow reviewer resubmission and atomic aggregation;
6. finding routing and the no-recheck author-owned revision/release policy;
7. course-level terminology, semantic-object and cross-deck continuity checks;
8. one-principal-teaching-move density auditing;
9. source and disposable-HTML mathematics checks, and the explicit absence of PDF math evidence;
10. targeted and full corrective-maintenance releases that preserve the base release;
11. author-side disposable-HTML overflow blocking and exclusion of mechanical reports from reviewer context;
12. course meeting organization, advisory lesson-time plans, mandatory course MCQs and academic-report exemption;
13. verified GeoGebra hyperlinks, allowed reuse and forbidden embedding;
14. extracted-text-only reference access, thread independence and exact token accounting without estimates;
15. unpinned Marp command construction, PDF-only durable output and doctor probe behavior; and
16. top-level-TASK-only digest policy, assignment contracts, policy reconfirmation and task audit.

## Static and project validation

The following checks passed in the working tree:

```bash
python scripts/validate_project.py --skip-tests
PYTHONWARNINGS=error python -m compileall -q src scripts tests
bash -n start.sh start-safe.sh
PYTHONPATH=src python -m mpres --help
PYTHONPATH=src python -m mpres log-daemon --help
PYTHONPATH=src python -m mpres maintenance --help
```

`validate_project.py` additionally:

- checks project version `0.5.0` in Python and Node metadata;
- parses all TOML, JSON, JSON Schema and YAML files, with duplicate-YAML-key detection;
- checks planner `Sol/max` and worker `Sol/high` in the global policy and Codex role files;
- verifies required v0.5.0 modules, skills and structured templates;
- rejects `package-lock.json`, stage-specific assignment templates, `MATH-PDF-EVIDENCE`, crash-recovery/workflow-freeze modules and numbered worker roles;
- checks that production logging routes through the daemon-backed single project log;
- checks CLI availability for logging, stages, review and maintenance;
- compiles project, scripts and tests and validates POSIX launcher syntax.

## External environment observed

Present in the build environment:

```text
Python 3.13.5
pytest 9.0.2
Node.js 22.16.0
npm 10.9.2
Playwright 1.57.0
Chromium 144.0.7559.96
pdftotext 25.06.0
Tesseract 5.5.0
```

`mpres.browser.browser_probe()` successfully launched `/usr/bin/chromium` and reported it available.

Not present:

```text
Codex CLI
local Marp CLI
Ruff
```

Therefore this record does **not** claim a real Codex multi-agent run or a real npm-installed Marp CLI → PDF smoke test in this container. Rendering tests use a deterministic Marp-compatible executable that produces real, parseable PDF files and disposable HTML for the production inspection path. On the target machine, production readiness still requires:

```bash
python scripts/bootstrap.py
.venv/bin/mpres doctor --strict
```

The doctor command must validate the locally installed, unpinned Marp CLI and the actual Chromium layout/PDF combination.

## Release-package verification

Before delivery, the source tree is cleaned of runtime and build products, archived, extracted into a new directory, and the following are rerun there:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python scripts/validate_project.py --skip-tests
PYTHONWARNINGS=error python -m compileall -q src scripts tests
bash -n start.sh start-safe.sh
```

The archive excludes task runtime data, `.venv`, `node_modules`, `.mpres`, browser caches, pytest/Ruff caches, `__pycache__`, bytecode, generated HTML/PDF, `package-lock.json`, checksum sidecars and source-manifest digests. In accordance with project policy, no archive checksum is generated.
