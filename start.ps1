param([switch]$Dev)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Set up dependencies first. Follow README.md.'
}
if (-not $Dev -and -not (Test-Path -LiteralPath 'frontend\dist\index.html')) {
    throw 'Build the frontend first: cd frontend; npm run build'
}
if ($Dev) {
    & $pythonPath -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
} else {
    & $pythonPath -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
}

