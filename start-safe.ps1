$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 scripts/bootstrap.py }
elseif (Get-Command python -ErrorAction SilentlyContinue) { & python scripts/bootstrap.py }
else { throw "Python 3.11 or newer was not found." }
$env:MPRES_ROOT = $Root
$env:PATH = "$(Join-Path $Root '.venv\Scripts');$(Join-Path $Root 'node_modules\.bin');$env:PATH"
& (Join-Path $Root ".venv\Scripts\python.exe") -m mpres.log_daemon start --root $Root | Out-Null
$Prompt = "Read AGENTS.md, docs/WORKFLOW.md, MODEL-POLICY.yaml, TOOLCHAIN-LOCK.yaml, and the relevant skills. Run the strict startup checks and continue a valid active task. If none exists, conduct the compact questionnaire and explain the binding policy: choose an explicit production profile; legacy migrations use exactly three migration stages while keeping one fixed author per lesson; every deck receives five isolated full-deck reviews and every reviewer reads the entire frozen deck; one deck revision author handles all findings after lesson authors close; reviewers do not recheck; screenshots/model vision and original-PDF worker access are forbidden; the main agent alone writes or revises TASK.md, but all other planner work may be delegated to max-reasoning planners; an approved batch plan may be mechanically expanded into exact unit assignments; review, revision, and release workers are created only when their gates are reached; the exact pinned toolchain must pass its smoke test; confirmed engine bugs require a policy amendment and separate repair work, never an in-task hot-patch; course lessons need 2–3 diagnostic MCQ prompt/answer pairs; output is Marp PDF; Python figures are disabled by default; GeoGebra is hyperlink-only; delivery modes are pilot/each/all. Use the persistent project log daemon. Do not initialize production before exact TASK.md confirmation."
& codex --strict-config --cd $Root --sandbox workspace-write --ask-for-approval on-request --search $Prompt
exit $LASTEXITCODE
