# Alertas del MVP

El resultado vigente se obtiene al ejecutar `run_analysis.ps1`; los conteos quedan en `analysis/alerts/alert_summary.json` y el detalle en `alerts.csv`. Solo se evalúa el periodo posterior al entrenamiento y solo se ejecutan las cinco reglas habilitadas.

Las alertas del demo se guardan con origen `csv_demo_mvp` en SQLite. Alta y crítica registran entrega interna `soc_inbox`; todas permanecen visibles y admiten los estados `new`, `notified`, `investigating`, `resolved` y `false_positive`.

Las reglas de horario nocturno/inusual y red UTPL permanecen desactivadas y no generan alertas. Los resultados históricos anteriores se conservan como archivos locales ignorados, pero no forman parte de la bandeja vigente.
