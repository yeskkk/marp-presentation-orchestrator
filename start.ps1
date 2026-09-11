$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Python = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { Join-Path $Root ".venv\Scripts\python.exe" }
if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) { throw "Install first: python scripts/bootstrap.py --with-figures (or set PYTHON_BIN)." }
$env:MPRES_ROOT = $Root
$OldPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = (Join-Path $Root "src") + $(if ($OldPath) { [IO.Path]::PathSeparator + $OldPath } else { "" })
    & $Python -m mpres.startup --root $Root @args
    $Code = $LASTEXITCODE
} finally { $env:PYTHONPATH = $OldPath }
exit $Code
