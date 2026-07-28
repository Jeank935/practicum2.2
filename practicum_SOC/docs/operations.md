# Operación

## Demostración local

1. Crear `.venv` e instalar `requirements.txt`.
2. Generar o configurar una clave HMAC externa.
3. Ejecutar `run_demo.ps1`.
4. Abrir `http://127.0.0.1:8000`.
5. Abrir una alerta, revisar evidencia y cambiar su estado.
6. Descargar el reporte desde `Reporte`.

No borre `analysis/state/soc_alerts.db`: contiene estados, historial, entregas y cooldown entre ejecuciones. El demo es idempotente; una segunda ejecución no vuelve a crear ni entregar la misma alerta.

## Política de entrega

- Alta/crítica: se guarda, se registra un intento `soc_inbox` y cambia a `notified`.
- Baja/media: se guarda y la entrega queda diferida por política.
- No existe salida a correo, Teams ni webhook en este MVP.

`soc_inbox` representa la propia bandeja SQLite/FastAPI. El canal definitivo debe acordarse con la Dirección.

## Live

Configure `.env` solo dentro del entorno autorizado. `run_monitor.ps1 -Source postgres -Mode once` consulta el siguiente lote; `-Mode loop` repite según `config/operational.json`. Ante fallo, aparece el mensaje de fallback y se usa el CSV.

El usuario PostgreSQL debe ser de solo lectura. Verifique permisos reales con la administración de base; la aplicación también declara la sesión `READ ONLY`.

## Mantenimiento

- Umbrales: `config/detection_rules.json`.
- Entrenamiento/evaluación: `config/baseline.json`.
- Intervalos/entrega: `config/operational.json`.
- Rechazos: `config/normalization.json`.
- Exclusiones autorizadas: `config/exclusions.json`.

Las exclusiones se registran únicamente mediante claves pseudonimizadas (`usr_...` e `ip_...`). No silencian completamente una fuente: elevan sus umbrales a los valores de `anomalous_thresholds`, por lo que un comportamiento excepcional todavía abre un caso. Los eventos normalizados permanecen disponibles para el reporte histórico.

Tras cualquier cambio, ejecute `pytest`, `ruff` y el análisis completo. Compare volumen por regla y falsos positivos antes de aprobar una configuración.

## Diagnóstico

| Síntoma | Acción |
|---|---|
| No inicia FastAPI | Instalar `requirements.txt` dentro de `.venv`. |
| Faltan artefactos | Ejecutar `run_analysis.ps1`. |
| No conecta PostgreSQL | Revisar red autorizada, vista y variables; no imprimir el DSN. |
| No llegan eventos live | Consultar `/health` y el checkpoint. |
| Alertas repetidas | Revisar fuente, ID, cooldown y `suppression_log`. |
| Pseudónimos cambiaron | Restaurar la misma clave HMAC. |
