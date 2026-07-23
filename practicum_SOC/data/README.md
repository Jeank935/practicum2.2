# Datos fuente

`INTEGRATIONDB_integrt_security_event_logs1.csv` es el origen oficial para este
proyecto. Contiene datos operativos reales y no debe publicarse ni incorporarse
al control de versiones.

El archivo no incluye encabezados. Su esquema posicional está documentado en
`../docs/data_dictionary.md`.

Los scripts leen este archivo sin modificarlo. Todos los resultados derivados
se escriben en `../analysis/` y los identificadores sensibles se
pseudonimizan antes del análisis.
