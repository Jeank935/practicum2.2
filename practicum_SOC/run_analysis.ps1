param(
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

$SourceCsv = "data\INTEGRATIONDB_integrt_security_event_logs1.csv"
$SecretFile = ".secrets\pseudonym_key.txt"

function Invoke-PythonStep {
    param(
        [string]$Label,
        [string[]]$Arguments
    )
    Write-Host "`n[$Label]" -ForegroundColor Cyan
    & $PythonExecutable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Falló el paso: $Label"
    }
}

if (-not (Test-Path -LiteralPath $SourceCsv)) {
    throw "No se encontró el CSV oficial: $SourceCsv"
}

Invoke-PythonStep "Pruebas" @("-m", "pytest", "-q")
Invoke-PythonStep "Clave de pseudonimización" @("tools\generate_secret.py", $SecretFile)
Invoke-PythonStep "Perfil de calidad" @(
    "tools\profile_csv.py", $SourceCsv,
    "--output", "analysis\data_profile.json"
)
Invoke-PythonStep "Normalización" @(
    "src\normalize_events.py", $SourceCsv,
    "--output", "analysis\normalized_events.csv",
    "--stats-output", "analysis\normalization_stats.json",
    "--rejected-output", "analysis\rejected_events.csv",
    "--config", "config\normalization.json",
    "--pseudonym-key-file", $SecretFile
)
Invoke-PythonStep "Línea base" @(
    "src\build_baseline.py", "analysis\normalized_events.csv",
    "--output-dir", "analysis\baseline",
    "--config", "config\baseline.json"
)
Invoke-PythonStep "Alertas históricas" @(
    "src\detect_alerts.py", "analysis\normalized_events.csv",
    "--output-dir", "analysis\alerts",
    "--config", "config\detection_rules.json",
    "--baseline-dir", "analysis\baseline"
)
Invoke-PythonStep "Reporte histórico" @(
    "src\generate_report.py",
    "--analysis-dir", "analysis",
    "--output-dir", "analysis\report",
    "--detection-config", "config\detection_rules.json"
)

Write-Host "`nAnálisis completado." -ForegroundColor Green
Write-Host "Resumen de línea base: analysis\baseline\baseline_summary.json"
Write-Host "Alertas: analysis\alerts\alerts.csv"
Write-Host "Resumen de alertas: analysis\alerts\alert_summary.json"
Write-Host "Reporte histórico: analysis\report\historical_report.md"
