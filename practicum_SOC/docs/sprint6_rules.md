# Sprint 6: reglas y puntajes versionados

La administración está en `/admin/rules`. Solo el rol **administrador** puede abrirla o utilizar `/api/v1/admin/rule-config`. El analista conserva la investigación y el cierre de casos, sin editar reglas. La autenticación, CSRF y los límites de solicitudes existentes protegen estas rutas.

## Flujo operativo

1. Abra **Reglas y puntajes** y cree un borrador a partir de la versión activa.
2. Cambie únicamente los campos expuestos de las cinco reglas disponibles. Puede ajustar ventanas, umbrales, pausa entre casos, puntaje base y bonificaciones. Los umbrales globales determinan la severidad resultante. La página muestra los valores activos junto a los del borrador.
3. Seleccione fuente y periodo histórico. La comparación muestra cuántos casos producirían ambas versiones por regla y severidad, tras simular deduplicación y pausa en memoria. No crea alertas, no mueve checkpoints y no modifica eventos.
4. Escriba una justificación y publique. La comparación debe corresponder al contenido actual del borrador y a la versión activa, y haberse realizado en los últimos 60 minutos. El siguiente ciclo del monitor toma la versión publicada.
5. Para revertir, seleccione una versión publicada anterior, escriba el motivo y pulse **Restaurar versión**. El historial conserva cada publicación y restauración con autor y fecha.

Las alertas nuevas guardan `rule_version_id`; las anteriores muestran «Anterior al versionado». Una publicación no recalcula ni borra casos existentes. El archivo `config/detection_rules.json` se usa para la primera versión y para los CLI históricos; una vez inicializada la base SOC, la versión activa vive en ella. Para cambiarla, use el flujo administrado. La pantalla de auditoría de archivos sigue indicando cambios externos, sin atribuirlos falsamente al administrador.

La simulación incluye eventos de contexto de hasta la mayor ventana configurada antes del inicio seleccionado, pero cuenta solo alertas cuya última evidencia cae en el periodo solicitado. Excluye los eventos de entrenamiento conforme a la línea base. Exige una línea base disponible y eventos de evaluación; si falta alguno, informa el problema. Se limita a 30 días y 10 000 eventos leídos para mantener predecible la carga; el periodo sugerido es de seis horas y, si se supera el límite, hay que reducirlo. Ajuste estos límites en `config/rule_management.json` después de medir el entorno. No consulta la fuente institucional: lee únicamente eventos normalizados ya guardados en PostgreSQL SOC o SQLite local. El resultado estima una ejecución aislada; no sustituye la revisión humana ni incorpora supresiones de casos ya persistidos por una ejecución anterior.

## Despliegue

SQLite agrega las tablas y la columna al abrirse con esta versión. Para el PostgreSQL SOC del despliegue Docker, actualice la imagen y ejecute `init` antes de reiniciar monitor y web:

```powershell
docker compose --env-file .env.docker --profile live stop worker
docker compose --env-file .env.docker build
docker compose --env-file .env.docker run --rm init
docker compose --env-file .env.docker up -d web grafana
```

El último comando no inicia el monitor live. Reanúdelo conforme a [la guía Docker](container_deployment.md) cuando corresponda. No elimine volúmenes. `init` solo prepara PostgreSQL propio del SOC.

## Dónde está cada pieza

| Archivo | Función |
| --- | --- |
| `src/rule_config_schema.py` | Tablas de versiones, borradores, comparaciones e historial; columna de versión en alertas. |
| `src/rule_config.py` | Validación, edición permitida, publicación, restauración y auditoría. |
| `src/rule_preview.py` | Replay limitado contra eventos guardados y comparación de resultados. |
| `src/rule_web.py` | Rutas administrativas HTML y API privada versionada. |
| `src/monitoring.py`, `src/demo_service.py` | Lectura de la versión activa al ejecutar y asignación de versión a casos. |
| `templates/rules.html`, `static/rules.js`, `static/rules.css` | Pantalla para comparar y publicar sin introducir código ni SQL. |
| `config/rule_management.json` | Límites de periodo, eventos e historial; vigencia de la comparación. |

## Verificación

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

Las pruebas PostgreSQL requieren `SOC_TEST_STORAGE_DSN` de una instancia **local de pruebas**; crean y eliminan sus propios esquemas. También se prueban los roles, CSRF, rangos inválidos, aislamiento del borrador, simulación sin escritura de casos, publicación, restauración y versión de cada alerta.
