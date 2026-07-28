param(
    [ValidateRange(1, 5000)]
    [int]$Limit = 500,
    [ValidateRange(1024, 65535)]
    [int]$Port = 8001,
    [string]$PythonExecutable = ""
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

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$RelativeStateDb = "analysis\state\soc_live_today_$Timestamp.db"
$StateDb = Join-Path $ProjectRoot $RelativeStateDb

& $PythonExecutable "src\live_sample_cli.py" --state-db $StateDb --limit $Limit
if ($LASTEXITCODE -ne 0) { throw "No fue posible preparar la muestra live" }

& $PythonExecutable "src\monitor_service.py" `
    --source postgres `
    --input-csv "data\INTEGRATIONDB_integrt_security_event_logs1.csv" `
    --state-db $StateDb `
    --detection-config "config\detection_rules.json" `
    --normalization-config "config\normalization.json" `
    --operational-config "config\operational.json" `
    --pseudonym-key-file ".secrets\pseudonym_key.txt" `
    --notification-mode "soc_inbox" `
    --batch-size $Limit `
    --once
if ($LASTEXITCODE -ne 0) { throw "Falló el análisis de la muestra live" }

$env:SOC_STATE_DB = $StateDb
Write-Host "`nMuestra live lista en http://127.0.0.1:$Port" -ForegroundColor Green
Write-Host "SQLite aislada: $RelativeStateDb"
Write-Host "Detenga la bandeja con Ctrl+C."
& $PythonExecutable -m uvicorn web_app:app --app-dir src --host 127.0.0.1 --port $Port
