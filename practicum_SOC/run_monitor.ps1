param(
    [ValidateSet("csv", "postgres")]
    [string]$Source = "csv",
    [ValidateSet("once", "loop")]
    [string]$Mode = "once",
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

$Arguments = @(
    "src\monitor_service.py",
    "--source", $Source,
    "--input-csv", "data\INTEGRATIONDB_integrt_security_event_logs1.csv",
    "--state-db", "analysis\state\soc_alerts.db",
    "--detection-config", "config\detection_rules.json",
    "--normalization-config", "config\normalization.json",
    "--operational-config", "config\operational.json",
    "--pseudonym-key-file", ".secrets\pseudonym_key.txt",
    "--notification-mode", "soc_inbox"
)

if ($Mode -eq "once") {
    $Arguments += "--once"
} else {
    $Arguments += "--loop"
}

& $PythonExecutable @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "El monitor finalizó con error"
}
