# F3.17 — Resultado incierto del commit SQLite (laboratorio)

**Estado:** pruebas de fallo inyectado en una conexión SQLite sintética, sin modificaciones del núcleo, API, esquema, interfaz o workflows. F3.16 ya está integrada en master.

## Diseño de la prueba

Se inyecta un fallo **una sola vez** en el método `sqlite3.Connection.commit()` de una conexión de laboratorio. Se deja pasar el primer commit de validación del esquema y se prueba la segunda confirmación, correspondiente a la UoW de transición de un pedido sintético.

1. **Excepción antes del commit real:** el método de prueba lanza `sqlite3.OperationalError` sin ejecutar `super().commit()`; la UoW intenta rollback. Una conexión nueva observa pedido en `draft` y los contadores de idempotencia/outbox sin cambios.
2. **Excepción después del commit real:** el método llama a `super().commit()` y después lanza `sqlite3.OperationalError`. La UoW observa la excepción, pero una conexión nueva encuentra `validated`, una clave idempotente y un único evento outbox.
3. **Respuesta HTTP indistinguible:** ambos escenarios responden con 500 sanitizado y `X-Request-ID`; el cuerpo no revela causa, detalles SQLite ni si el commit se aplicó.
4. **Reconciliación:** una repetición del POST **idéntico** con la misma `Idempotency-Key` recupera 200 sin duplicados, en ambos casos. Un intento posterior con clave nueva da 409. El pedido del otro negocio permanece intacto.

La excepción se inyecta exclusivamente mediante un `sqlite3.Connection` de pruebas en una base temporal, y se desactiva antes del reintento. No se cambia `SqliteUnitOfWork` ni se introduce retry automático. El objetivo es comprobar una **indeterminación observable por el cliente**, no convertir HTTP 500 en un protocolo de idempotencia.

## Límites y condiciones

Se trata de una **inyección determinista de excepción**, no de una caída de máquina, fallo de fsync, corte eléctrico ni terminación de proceso durante el commit SQLite. No demuestra durabilidad ante fallos físicos, orden total distribuido ni garantías en PostgreSQL. Aunque tras inyectar el fallo la base revele uno de dos estados, el cliente real no puede deducirlo de la respuesta HTTP; debe mantener el mismo ámbito/pedido/acción/clave, consultar el estado si está autorizado y repetir con límites de intentos.

Solo desarrollo y pruebas con SQLite y datos sintéticos. CI requerida: `python -m pytest -q`, `ruff check .`, `ruff format --check .`, `mypy src` en Python 3.11 y 3.12. Pendiente revisión de PR y merge; React e identidad productiva permanecen desactivados.
