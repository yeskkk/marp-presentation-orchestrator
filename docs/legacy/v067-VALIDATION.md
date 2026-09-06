# Validation record — v0.6.7

Validation date: 2026-09-03 UTC.


## v0.6.7 incremental gates

- A repeated scaffold creates only missing files and preserves every existing assignment-contract byte.
- An approved or revoked incomplete contract fails closed rather than regenerating unknown planner content.
- Exact repeated approval preserves actor, notes, timestamp, and file bytes; revision requires explicit revoke and reapproval increments the sequence.
- Unit expansion records operational history separately and does not mutate an approved batch plan.
- Author, lesson, reviewer, revision, maintenance, diagnostic, and mechanical job retries preserve drafts and canonical evidence while repairing missing generated files.
- Concurrent same-identity scaffolds converge on one complete contract without replacement.

The release is validated in the clean worktree and again after extracting the final source ZIP. Each pytest module runs in its own process so the persistent logging-daemon fixtures cannot retain the parent capture pipe.

## v0.6.1 incremental gates

- Every new task contains `TASK-RUNTIME-PROFILE.yaml`; its template defaults are planner `gpt-5.6-sol/high`, author `gpt-5.6-sol/medium`, and reviewer `gpt-5.6-sol/low`.
- The presented runtime profile is part of the confirmation snapshot, but no additional hash is created. Any post-confirmation edit invalidates the task gate.
- Project Codex and agent TOML files contain no concrete model or reasoning choice.
- Production initialization fails until the exact token collector is initialized.
- Token reports preserve unknown values as null and expose known subtotals, unknown counts, and coverage.

## Policy represented by this release

This release implements the production-control changes adopted after the
`linear-algebra-for-economics-intuitive-marp-v3` run:

- `legacy_migration` bypasses the greenfield six-stage graph and uses exactly
  `m01_baseline_audit`, `m02_delta_design_patch`, and
  `m03_integration_semantic_check`;
- every lesson still has one fixed lesson author for all of its authoring
  stages;
- the planner approves one semantic `BATCH-ASSIGNMENT-PLAN.yaml`, after which
  the control plane mechanically expands unit assignments without inventing
  new scope or acceptance criteria;
- only writing or revising top-level `TASK.md` is exclusive to the main agent;
  every other planner operation may be delegated to a planner worker;
- unit workspaces, five specialist reviewers, the deck revision author, and
  the mechanical release job is registered only when their critical-path state is
  reached;
- lesson authors may close after durable handoff; one deck revision author
  receives the compiled context packet and owns every post-review edit;
- all five independent reviewers read the complete frozen deck, and their
  handoffs are atomically aggregated;
- a confirmed workflow-engine technical defect cannot be hot-patched inside
  the task: it creates `ENGINE-INCIDENT.yaml` and a task policy amendment,
  after which the main agent revises `TASK.md` for user reconfirmation;
- Marp CLI is exactly pinned to `4.5.0`, and a three-slide toolchain smoke test
  is a production precondition;
- the critical-path scheduler prioritizes the current review/revision/release,
  then the current presentation, then the next ready presentation; speculative
  future model workers are forbidden;
- canonical delta, context, interaction, review, incident, milestone, and
  performance records replace independently editable duplicate evidence;
- one project-level logging daemon remains the only writer of
  `logs/project.jsonl`; routine transitions are control-plane events rather
  than model supervision calls;
- screenshots, model vision, worker access to original reference PDFs,
  persistent HTML, reviewer recheck after revision, and hashes outside the
  confirmed top-level `TASK.md` remain forbidden.

## Automated regression

The complete regression suite is run with third-party pytest plugin autoload
disabled. Each test module runs in a fresh process because the logging-daemon
fixtures intentionally exercise persistent subprocess behavior:

```bash
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export PYTHONPATH=src
for module in tests/test_*.py; do python -m pytest -q "$module"; done
```

Final result:

```text
99 passed
```

The tests cover, among other things:

1. production-profile selection, the exact migration stage graph, and fixed
   lesson-author ownership;
2. planner-approved batch expansion and the main-agent-only `TASK.md` rule;
3. lazy unit workspace creation, critical-path activation, and just-in-time
   reviewer, revision-author, and mechanical release-job registration;
4. author-context compilation, deterministic finding routing, one deck-level
   revision owner, and no reviewer recheck;
5. five isolated full-deck review channels and atomic aggregation;
6. workflow-engine incident records, task blocking, policy amendment, and
   reconfirmation requirements without an in-task hotfix path;
7. exact Marp version enforcement, the three-slide smoke-test contract, Marp
   4.5 SVG slide discovery, explicit DOM readiness, and size-aware rendering
   timeouts;
8. global course meeting numbers distinct from deck-local ordinals;
9. canonical interaction records and generated compatibility views;
10. source, density, course-consistency, mathematical-typesetting, HTML
    overflow, PDF structure, and text-layer inspection;
11. project logging, thread lifecycle, checkpoints, supervision, task-local immutable runtime selection, collector startup gating, and null-safe exact milestone token accounting;
12. targeted and full corrective maintenance without overwriting prior
    releases; and
13. task confirmation, assignment contracts, reference safety, asset policy,
    GeoGebra links, and terminology continuity.

## Static and project validation

The release validator runs:

```bash
PYTHONPATH=src python scripts/validate_project.py --skip-tests
PYTHONWARNINGS=error python -m compileall -q src scripts tests
bash -n start.sh start-safe.sh
PYTHONPATH=src python -m mpres --help
PYTHONPATH=src python -m mpres assignment --help
PYTHONPATH=src python -m mpres production --help
PYTHONPATH=src python -m mpres review --help
PYTHONPATH=src python -m mpres toolchain --help
PYTHONPATH=src python -m mpres engine --help
```

`validate_project.py` also:

- checks project version `0.6.1` in Python and Node metadata;
- parses all TOML, JSON, JSON Schema, and YAML files, rejecting duplicate YAML
  keys;
- checks that runtime selection is task-local, that project and role TOML files do not hard-code model/effort, and that the default planner/author/reviewer profile is high/medium/low;
- verifies the required v0.6.0 control-plane modules plus the v0.6.1 runtime-profile and token-accounting additions, roles, skills, canonical
  records, migration stages, and assignment templates;
- rejects obsolete duplicate legacy/interaction templates, old-version tests,
  stage-specific assignment templates, numbered worker roles,
  `MATH-PDF-EVIDENCE`, recovery/workflow-freeze subsystems, and forbidden npm
  lock files;
- verifies migration/profile separation, planner delegation, fixed lesson
  authors, lazy initialization, full-deck five-reviewer scope, deck-level
  revision, the no-hotpatch engine policy, and the exact Marp lock;
- checks the critical-path priority order, daemon-backed single project log,
  CLI surface, launcher syntax, bytecode compilation, and stale-policy text.

## External environment observed

Present in the build environment:

```text
Python 3.13.5
pytest 9.0.2
Node.js 22.16.0
npm 10.9.2
Playwright installed
Chromium 144.0.7559.96
pdftotext 25.06.0
```

The automated tests use deterministic browser/Marp fixtures where external
installation independence is required. This record therefore does not claim a
real npm-installed Marp-to-PDF smoke run in the release container. On every
target installation, production remains blocked until these commands pass
against the actual local toolchain:

```bash
python scripts/bootstrap.py
.venv/bin/mpres doctor --strict
.venv/bin/mpres toolchain smoke
```

## Release-package verification

The source archive excludes `.git`, virtual environments, `node_modules`, task
runtime data, `.mpres`, browser/test/lint caches, bytecode, generated HTML/PDF,
and other build products. The archive is extracted into a fresh directory and
is checked again with:

```bash
PYTHONPATH=src python scripts/validate_project.py --skip-tests
PYTHONWARNINGS=error python -m compileall -q src scripts tests
bash -n start.sh start-safe.sh
PYTHONPATH=src python -m mpres --help
```

No archive checksum or source-manifest digest is generated, in accordance with
the policy that only the task's top-level `TASK.md` receives a confirmation
digest.

## v0.6.2 incremental validation

Scope: remove the model-based `review-coordinator` and `release-coordinator` and replace their work with runtime-free Python control-plane jobs.

Verified in the clean v0.6.2 worktree:

- the complete repository test collection contains 50 tests and completed with exit code 0;
- the three new v0.6.2 mechanical-control tests passed independently;
- all five v0.6.1 runtime/token tests remained unchanged and passed;
- `python -m py_compile src/mpres/*.py scripts/validate_project.py` passed;
- `PYTHONPATH=src python scripts/validate_project.py --skip-tests` passed;
- `git diff --check` passed.

The release archive is accepted only after a second clean extraction repeats the static checks, CLI smoke test, and complete test suite. The machine-readable verification report accompanies the archive.


## v0.6.3 incremental validation

- The scheduler uses one shared predicate for automatic rebalancing and explicit activation.
- The next authoring lane remains available throughout current-deck authoring, review, revision, and release-ready states.
- Entering full review automatically activates and lazily materializes exactly the earliest next authoring deck in `all` mode.
- `each`, the initial `pilot` pause, and `next_presentation_authoring_wip_limit: 0` still prevent overlap.
- Work-plan projection distinguishes the current review/revision/release lane from the concurrent next authoring lane.

## v0.6.4 incremental validation

Scope: replace concurrent whole-file read-modify-write of task state and the thread registry with one task-local transactional store, while retaining JSON/YAML projections.

Release validation covers:

- stale-snapshot compare-and-swap rejection without lost updates;
- concurrent command serialization under a reentrant task transaction;
- rollback of both canonical task state and projections after an exception;
- concurrent thread registration preserving every handle;
- automatic first-read import and projection repair for a v0.6.3 task;
- five reviewer-channel submissions completing concurrently without erasing one another;
- policy audit and `task transaction-status` visibility;
- all v0.6.1 runtime/token, v0.6.2 mechanical control, and v0.6.3 pipeline tests remaining green.

Worktree acceptance result for this milestone:

```text
14 test files
71 tests passed
0 failed
```

The release archive must repeat the same 71-test per-file suite after clean extraction.

## v0.6.5 incremental validation

Focused tests cover first-occurrence compatibility, concurrent counting, suspected occurrences,
exact confirmation, post-presentation tamper rejection, gate-wide blocking, and verified closure.

## v0.6.6 incremental validation

The release gate additionally verifies: bounded target/neighbor extraction; slide-ID and page resolution; target and evidence caps; read-only evidence and result directories; no PDF artifacts in cases; fixed reviewer-family runtime; planner assignment approval; rejection of out-of-packet evidence or patch scope; explicit low-confidence scope expansion; published-source preservation; diagnostic CLI help; diagnostic log kind; and full v0.6.5 regression compatibility.

## v0.6.7 incremental validation

Twelve focused tests cover create-only author, lesson, reviewer, maintenance, diagnostic, and control-job recovery; byte-preserving repeated approval; explicit revoke/reapproval sequencing; approved-incomplete fail-closed behavior; separate batch-expansion state; same-identity concurrency; and conflicting concurrent semantic requests.

Final acceptance for the clean worktree and independently extracted source package is:

```text
17 test modules
99 tests passed
0 failed
```
