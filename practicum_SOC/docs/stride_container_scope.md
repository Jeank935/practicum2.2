# STRIDE: ajuste de alcance para la entrega Docker

El modelo de referencia entregado no acredita controles implementados ni cambia
las reglas. Este complemento alinea el despliegue con el acuerdo del Sprint 0.

## Roles objetivo: solamente dos

| Capacidad | Administrador | Analista |
|---|---|---|
| Dashboards, alertas e investigación | Sí | Sí |
| Cambiar estados y registrar evidencia | Sí | Sí |
| Configurar reglas y puntajes con trazabilidad | Sí | No |
| Administrar usuarios y asignar roles | Sí | No |

El acceso OIDC local y la autorización de operadores están implementados. La
configuración versionada de reglas mediante interfaz es exclusiva del administrador.
Identificar a una persona
requiere consulta institucional autorizada; el HMAC no es reversible.
Los roles internos de PostgreSQL y Grafana son cuentas técnicas, no nuevos
perfiles funcionales de usuario del SOC.

## Reglas vigentes

La fuente de verdad continúa siendo config/detection_rules.json y
src/practicum_soc/soc/detection.py. No se adoptan automáticamente ventanas, umbrales ni nuevas
reglas del Word. Los puntajes STRIDE (amenazas al sistema) no son los scores
del detector (señales de autenticación). Se conserva su catálogo actual.

## Límites y controles

| Categoría | Medida de esta entrega | Pendiente institucional |
|---|---|---|
| Suplantación | Keycloak OIDC con PKCE, firma y sesiones acotadas; Grafana privado | MFA, HTTPS y dominio institucional |
| Manipulación | Fuente de solo lectura; deduplicación, transacciones y reglas versionadas con publicación auditada | Custodia de evidencias y aprobación institucional de parámetros |
| Repudio | Consultas y estados de casos con operador; cambios de usuarios con antes/después; huellas de configuración desplegada | Auditoría resistente a alteración; atribución de cambios externos mediante el proceso de entrega |
| Divulgación | HMAC, imágenes sin .env/CSV, Grafana solo vista agregada | HTTPS, permisos de exportación y resolución de identidad |
| Denegación de servicio | Métricas preagregadas; límites persistentes y atómicos por operación/operador; login por IP de conexión | Pruebas de carga de clases, protección del proxy y alertas operativas |
| Elevación de privilegios | Gestión de usuarios solo administrador; revocación de sesiones; permisos consultados en servidor | Revisión institucional de permisos y pruebas de penetración |

PostgreSQL de origen → procesador → PostgreSQL SOC → web/Grafana son límites de
confianza distintos. Solo el procesador recibe credenciales del origen. El
servicio init tiene privilegios elevados únicamente sobre la base SOC local.
No se conecta el datasource de Grafana a la fuente institucional.

Retención: propuesta inicial de 30 días, pendiente de aprobación y de definir
excepciones para casos/evidencia que necesiten más tiempo. No se activa borrado automático.
Dominio interno, acceso de red y operación los adapta UTPL. Este piloto NO está
listo para exposición pública; el acceso multiusuario local debe trasladarse a
HTTPS y al dominio aprobado antes de abrirlo a la red institucional.
