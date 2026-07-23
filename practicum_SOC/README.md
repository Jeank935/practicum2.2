# MVP SOC para autenticaciones ADFS

Aplicación local para normalizar eventos ADFS, construir una línea base sin fuga temporal, detectar anomalías explicables y gestionarlas desde una bandeja SOC. El CSV original se abre en solo lectura y nunca se modifica. Usuarios, IP cliente y origen lógico se pseudonimizan con HMAC-SHA256 antes de aparecer en salidas, SQLite, reportes o interfaz.

El sistema apoya a un analista SOC: prioriza señales y conserva evidencia. No confirma ataques, no bloquea cuentas y no modifica ADFS ni PostgreSQL.

## Inicio rápido del modo demo

Requisitos: Windows PowerShell y Python 3.11 o superior. El CSV debe conservarse en `data/INTEGRATIONDB_integrt_security_event_logs1.csv`.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe tools\generate_secret.py .secrets\pseudonym_key.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_demo.ps1
```

Abra `http://127.0.0.1:8000`. `run_demo.ps1` ejecuta pruebas, normalización, línea base, detección, reporte, persistencia SQLite y finalmente inicia FastAPI. Para omitir el reprocesamiento histórico cuando los artefactos ya existen:

```powershell
.\run_demo.ps1 -SkipAnalysis
```

## Flujo demostrado

1. `normalize_events.py` valida el CSV, deduplica por ID o huella determinista y separa válidos/rechazados.
2. `build_baseline.py` entrena con 2026-03-14 a 2026-03-20 y reserva los días posteriores para evaluación.
3. `detect_alerts.py` ejecuta exclusivamente las cinco reglas aprobadas para el MVP.
4. `AlertStore` guarda eventos, alertas, cooldown, entregas e historial de estados en SQLite.
5. `soc_inbox` registra internamente la entrega de alertas altas/críticas y las marca `notified`.
6. FastAPI y Jinja2 muestran el resumen, evidencia, entrega y estado.
7. `generate_report.py` crea `analysis/report/historical_report.md` de forma reproducible.

Salidas principales:

- `analysis/normalized_events.csv`
- `analysis/rejected_events.csv`
- `analysis/normalization_stats.json`
- `analysis/baseline/`
- `analysis/alerts/`
- `analysis/state/soc_alerts.db`
- `analysis/report/historical_report.md`

Todas son salidas operativas ignoradas por Git. `analysis/inconsistent_events.csv` se conserva como artefacto histórico anterior, pero el flujo vigente usa `rejected_events.csv`.

## Reglas activas

- múltiples fallos contra un usuario;
- una IP intentando acceder a varias cuentas;
- éxito después de múltiples fallos;
- bloqueo explícito de cuenta;
- IP nueva para un usuario con historial suficiente.

Las reglas de horario nocturno/inusual y red externa están desactivadas en `config/detection_rules.json`. No producen alertas: faltan cobertura temporal completa y CIDR/NAT/proxy/VPN oficiales.

## Estados y API

Estados permitidos: `new`, `notified`, `investigating`, `resolved` y `false_positive`.

Endpoints:

- `GET /` y `GET /alerts`
- `GET /alerts/{id}`
- `PATCH /alerts/{id}/status`
- `GET /health`
- `POST /demo/run`
- `GET /reports/latest`

La bandeja permite cambiar estados sin editar SQLite manualmente. `soc_inbox` es solo un canal de demostración; correo o Teams deben acordarse con la Dirección y pueden implementarse después mediante `NotificationProvider`.

## Modo live

Copie `.env.example` a `.env` y complete sus valores solo dentro de la red autorizada. La cuenta debe disponer exclusivamente de `SELECT` sobre una vista acordada.

```powershell
Copy-Item .env.example .env
.\run_monitor.ps1 -Source postgres -Mode once
```

El adaptador abre una sesión `READ ONLY`, consulta solo eventos posteriores al checkpoint `(event_time, event_id)` y nunca escribe en PostgreSQL. Si la configuración o conexión institucional no está disponible, informa `Fuente institucional no disponible. Utilizando modo demo` y usa el CSV local.

## Calidad y pruebas

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check .
```

Las pruebas utilizan datos sintéticos y mocks; no requieren red UTPL. Consulte `docs/architecture.md`, `docs/rules_catalog.md`, `docs/operations.md` y `docs/security.md`.

Para preparar una exposición del proyecto, consulte
`docs/defense_guide.md`, que relaciona cada entregable y criterio de aceptación
con sus archivos, bloques de código, pruebas y salidas demostrables.
