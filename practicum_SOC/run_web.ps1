param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000,
    [string]$HostAddress = "127.0.0.1",
    [string]$PythonExecutable = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot

if (-not $PythonExecutable) {
    $VirtualPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $VirtualPython)) {
        throw "No se encontró .venv. Ejecute: py -3.11 -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
    }
    $PythonExecutable = $VirtualPython
}

Write-Host "Bandeja SOC disponible en http://${HostAddress}:$Port" -ForegroundColor Green
Write-Host "Detenga el servidor con Ctrl+C."
& $PythonExecutable -m uvicorn web_app:app --app-dir src --host $HostAddress --port $Port

if ($LASTEXITCODE -ne 0) {
    throw "La plataforma finalizó con error"
}
