# Grafana: comparación de servicios

Extensión puntual del tablero existente. Modo Operate: el analista compara servicios y abre casos, sin cambiar reglas ni la identidad visual nativa de Grafana.

## Direction contract

THESIS: mostrar oscilaciones simultáneas y priorizar casos abiertos; no esconder el conjunto detrás de una selección individual.

OWN-WORLD: conservar paneles, controles, tipografía y tema de Grafana. Colores por serie distinguen servicios; severidades son contexto de casos, no prueba de ataque.

STORY: seleccionar Todos o varios servicios, comprobar las fechas y el monitor, comparar curvas y abrir la evidencia del servicio prioritario.

FIRST VIEWPORT: fechas y filtros arriba; indicadores de última actividad y ciclo; curva comparativa a ancho completo. Debajo, ranking y tabla ordenados por casos abiertos. Detalle individual disponible por enlace.

FORM: extensión precisa del dashboard provisionado; sin torneo ni seed, sin reemplazar el sistema visual. Interacción principal: leyenda para aislar curvas y enlaces de tabla que conservan servicio, fuente y fechas.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

No hay rasters nuevos ni cambios de identidad. El detalle individual conserva comparación con entrenamiento; sin muestras suficientes no se inventa una referencia. No hay datos recientes significa un rango vacío, no ausencia de ataques.

## Verificación de extensión

Esta entrega amplía el tablero incumbente, no sustituye su sistema visual. Se conserva `services.json` (vista por minuto), así como tema, tipografía, filtros, leyendas y paneles nativos de Grafana. Para este cierre de extensión, la referencia es el sistema existente: no se crea `DESIGN.md`, sidecar ni CSS/tokens externos.

Se revisaron `oscillations.json`, `service_detail.json`, `README.md` y `docs/sprint5_grafana.md`, y las capturas de escritorio, móvil y tabla. Los artefactos mantienen All/multiselección, prioridad por casos abiertos sin ocultar el total de alertas, indicadores separados de datos y ciclo del monitor, y enlaces que transportan servicio, fuente y fechas al detalle o a casos. Los Stat usan tamaños de texto explícitos y distribución vertical nativa; en móvil los paneles se apilan y el texto del monitor es más pequeño. Las capturas verifican composición y lectura, no autorizaciones ni ejecución de cada enlace.

Mantenimiento: conservar estas distinciones y el dashboard por minuto; no interpretar huecos como ceros ni alertas como ataques confirmados. Antes de cambiar títulos, campos de enlace o tamaños Stat, comprobar de nuevo escritorio y móvil, incluidos nombres largos. La documentación operativa explica fechas históricas, estados abiertos y límites de conteo; no duplicar aquí resultados variables ni datos privados.
