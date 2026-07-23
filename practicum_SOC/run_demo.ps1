param(
    [string]$PythonExecutable = "",
    [switch]$SkipAnalysis,
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot

if (-not $PythonExecutable) {
    $VirtualPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    $PythonExecutable = if (Test-Path -LiteralPath $VirtualPython) { $VirtualPython } else { "python" }
}

if (-not $SkipAnalysis) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File ".\run_analysis.ps1" `
        -PythonExecutable $PythonExecutable
    if ($LASTEXITCODE -ne 0) { throw "Falló el análisis histórico" }
}

& $PythonExecutable "src\demo_cli.py"
if ($LASTEXITCODE -ne 0) { throw "No fue posible poblar la bandeja SOC" }

Write-Host "`nBandeja SOC disponible en http://127.0.0.1:$Port" -ForegroundColor Green
Write-Host "Detenga el servidor con Ctrl+C."
& $PythonExecutable -m uvicorn web_app:app --app-dir src --host 127.0.0.1 --port $Port
