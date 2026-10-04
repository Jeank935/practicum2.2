---
version: 1
slug: "deploy-grafana-dashboards-oscillations-json"
primary_target: "deploy/grafana/dashboards/oscillations.json"
related_targets: []
---

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
