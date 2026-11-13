# F3.14 — Contención SQLite en transiciones de personal (laboratorio)

**Estado:** cambio localizado en adaptador API y pruebas. Exclusivamente SQLite temporal y datos sintéticos, sin despliegue ni activación del panel privado.

## Contrato

El adaptador `SqliteStaffOrderTransitions` diferencia explícitamente los códigos extendidos SQLite cuya clase primaria es `SQLITE_BUSY` o `SQLITE_LOCKED`. En esas condiciones eleva `StaffTransitionBusy` al borde HTTP, que devuelve **503 service_unavailable**, mensaje sanitizado y `Retry-After: 1`. El middleware conserva `X-Request-ID` y el puerto optativo F3.12 registra código 503 sin datos sensibles. No se devuelve el mensaje interno de SQLite ni se etiquetan como reintentables otras excepciones `OperationalError`, corrupción de datos o incompatibilidades de esquema.

El encabezado **no garantiza** que repetir la operación sea seguro con una clave nueva. El cliente debe **reconciliar el resultado y repetir con la misma Idempotency-Key**, sin presuponer que el commit no se aplicó si una respuesta se perdió o un error ocurrió tras él. No se introducen reintentos implícitos ni se modifican la UoW, los puertos de núcleo o el timeout por defecto de SQLite.

## Evidencia automatizada

- Un escritor externo retiene `BEGIN IMMEDIATE` durante una petición HTTP con conexión de timeout corto (solo inyección de test). Debe resultar 503, sin estado modificado ni filas nuevas de idempotencia/outbox.
- Liberado el bloqueo, la misma solicitud con igual clave produce una transición 200, una única fila de idempotencia y una única entrada outbox. El replay posterior no duplica escrituras.
- La auditoría optativa registra 503, correlación y sujeto autenticado, sin pedido ni credenciales.

## Límites

No se ha evaluado comportamiento bajo varios procesos, fallos en commit ambiguo, bloqueos de lectura, saturación persistente, discos remotos, ni PostgreSQL. `Retry-After` es orientación de laboratorio; el consumidor real debe implementar backoff con límite y reconciliación. SQLite se mantiene solo para desarrollo y pruebas.

Validaciones exigidas antes de integrar: `python -m pytest -q`, `ruff check .`, `ruff format --check .`, `mypy src` con Python 3.11 y 3.12. F3.12 y F3.13 aún son dependencias de esta rama y deberán revisarse por orden.
