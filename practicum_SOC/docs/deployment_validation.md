# Validación del despliegue portable

Verificación local realizada el 18 de septiembre de 2026. No se consultó la
base institucional ni se utilizaron credenciales o logs UTPL en estas pruebas.

## Resultados

- pytest: **43 pruebas aprobadas**, incluyendo tres integraciones contra un
  PostgreSQL 18 temporal local.
- ruff check: sin errores.
- ruff format --check: sin cambios pendientes.
- git diff --check: sin errores de espacios.
- Docker: construcción de la imagen Python y arranque de PostgreSQL, init, web
  y Grafana en un proyecto de prueba independiente.
- /health: web conectada a PostgreSQL SOC.
- Grafana: datasource saludable, dashboard provisionado y consulta SQL real
  devolviendo el contador sintético esperado.
- Deduplicación: insertar dos veces el mismo evento no duplica el agregado.
- Rollback: evento y agregado se revierten juntos.
- Evento tardío: se agrega al minuto original, incluso con offset horario.
- Separación de fuentes: no se mezclan los contadores demo y live.
- Persistencia: estado, checkpoint, notificación y cooldown sobreviven a reabrir
  la conexión.
- Privacidad: el lector de métricas no puede consultar eventos ni modificar
  contadores; la vista no expone IP, usuario ni URL del servicio.
- Pipeline CSV sintético: normaliza, separa entrenamiento, detecta, persiste,
  genera reporte y vuelve a ejecutarse sin duplicar; CSV original intacto.

El primer puerto PostgreSQL de prueba estaba reservado por Windows; se utilizó
otro puerto local libre. La etiqueta mayor de Grafana no estaba publicada; se
reemplazó por el digest de una imagen oficial descargable y se repitió el smoke
test correctamente. No son fallos pendientes del detector.

Los contenedores y volúmenes del smoke test se retiraron después de validar.
El PostgreSQL temporal fue detenido. No se dejó desplegada una instancia
institucional ni se migró el SQLite existente.

## Repetir la comprobación Docker

```powershell
.\.venv\Scripts\python.exe tools/smoke_containers.py
```

Usa puertos locales 18000 y 13000, secretos aleatorios en memoria y recursos con
nombre soc-smoke aleatorio. Elimina únicamente sus propios volúmenes al terminar.
No carga .env. Requiere Docker Desktop y acceso al registro de imágenes.

## Pendientes que esta validación no cubre

OIDC y autorización de dos roles, HTTPS y dominio, publicación en la red UTPL,
tráfico real en clases, retención aprobada, backups y restauración, migración
histórica del SQLite y revisión institucional de seguridad.
El CSV real no se ha reprocesado como parte de esta validación.
