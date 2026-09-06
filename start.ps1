$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { Join-Path $Root ".venv\Scripts\python.exe" }
if (-not (Test-Path $Python)) { throw "Install first: python scripts/bootstrap.py, or set PYTHON_BIN." }
$env:MPRES_ROOT = $Root
$CommandArgs = @($args)
if ($CommandArgs.Count -eq 0) { $CommandArgs = @("--help") }
& $Python -m mpres --root $Root @CommandArgs
exit $LASTEXITCODE
