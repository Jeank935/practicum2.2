# Auditoría inicial y plan ejecutado

## Estado encontrado

El repositorio contenía un flujo histórico funcional con perfilado,
normalización HMAC, línea base, cinco reglas iniciales, seis pruebas y un
ejecutor PowerShell. El CSV oficial tenía 100.000 filas válidas de ancho, sin
encabezado ni filas completamente duplicadas.

No existían conector PostgreSQL, checkpoint, almacenamiento operativo,
notificaciones, ciclo de estados, puntaje explicable, reporte ni API/CLI de
operación.

## Calidad observada

- 73.516 éxitos, 13.522 fallos y 12.962 bloqueos.
- 7 fechas de evento no utilizables (1970).
- 2 contradicciones entre nombre e ID de evento.
- 779 filas sin IP cliente.
- 1 fila sin usuario.
- 1.792 filas con `created_at` anterior al evento.
- `custom_user_id` y `custom_ip_address` son los campos analíticos correctos.
- `username` es una cuenta técnica; `source_ip`/`destination_ip` identifican
  servidores, no el origen del usuario.

## Riesgos encontrados

- README desactualizado respecto al motor ya existente.
- Valores operativos visibles en el perfil JSON.
- Registros inconsistentes no separados.
- Línea base no conectada con el detector.
- Cooldown solo en memoria y alertas solo en CSV.
- Sin control de entrega, estados ni checkpoint.
- 15.565 señales nocturnas: volumen no apto para notificación.
- Cobertura consistente de solo 12 horas locales.
- Sin CIDR oficiales para la regla de red.
- Sin ubicación ni perfil institucional en el modelo.

## Fases ejecutadas

1. Auditoría y reproducción del flujo original.
2. Privacidad, inconsistencias y deduplicación histórica.
3. Línea base temporal con suficiencia por usuario.
4. Catálogo ampliado y riesgo 0–100 explicable.
5. SQLite, checkpoint, cooldown persistente y ciclo de estados.
6. Fuente PostgreSQL de solo lectura y simulador CSV.
7. Interfaz `NotificationProvider` y canal local `soc_inbox`, sin comunicaciones externas.
8. Exclusiones autorizadas y registro de supresiones.
9. Informe histórico, gráficas y resumen periódico.
10. CLI de salud, consulta y estados.
11. Ampliación de pruebas y documentación operativa.

## Decisiones conservadoras

- No se activó ningún envío real.
- No se inventaron tabla/vista, credenciales, CIDR, ubicaciones o perfiles.
- No se implementó bloqueo automático.
- No se incorporaron servicios externos.
- La API FastAPI se pospuso porque el CLI cubre la operación mínima y el núcleo
  no debe depender de paquetes web.
- Las comparaciones con línea base solo se aplican después del periodo de
  entrenamiento.
