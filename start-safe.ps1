$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 scripts/bootstrap.py }
elseif (Get-Command python -ErrorAction SilentlyContinue) { & python scripts/bootstrap.py }
else { throw "Python 3.11 or newer was not found." }
$env:MPRES_ROOT = $Root
$env:PATH = "$(Join-Path $Root '.venv\Scripts');$(Join-Path $Root 'node_modules\.bin');$env:PATH"
$Prompt = "Read AGENTS.md, docs/WORKFLOW.md, and the marp-presentation-workflow skill. Run startup checks. If no task exists, conduct the questionnaire and warn about three rounds, no screenshots, medium default reasoning, PDF-only Marp output, disabled Python figures, optional GeoGebra-only hyperlink enrichment, and delivery choices."
& codex --strict-config --cd $Root --sandbox workspace-write --ask-for-approval on-request --search $Prompt
exit $LASTEXITCODE
