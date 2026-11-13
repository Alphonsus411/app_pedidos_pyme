# F3.17 — Resultado incierto del commit SQLite (laboratorio)

**Estado:** pruebas de fallo inyectado en una conexión SQLite sintética, sin modificaciones del núcleo, API, esquema, interfaz o workflows. F3.16 ya está integrada en master.

## Diseño de la prueba

Se inyecta un fallo **una sola vez** en el método `sqlite3.Connection.commit()` de una conexión de laboratorio. Se deja pasar el primer commit de validación del esquema y se prueba la segunda confirmación, correspondiente a la UoW de transición de un pedido sintético.

1. **Excepción antes del commit real:** el método de prueba lanza `sqlite3.OperationalError` sin ejecutar `super().commit()`; la UoW intenta rollback. Una conexión nueva observa pedido en `draft` y los contadores de idempotencia/outbox sin cambios.
2. **Excepción después del commit real:** el método llama a `super().commit()` y después lanza `sqlite3.OperationalError`. La UoW observa la excepción, pero una conexión nueva encuentra `validated`, una clave idempotente y un único evento outbox.
3. **Excepción indistinguible en el adaptador:** ambos escenarios generan el mismo `sqlite3.OperationalError` inyectado, aunque uno deja la transacción revertida y el otro confirmada. La prueba **no** atraviesa el borde HTTP durante la inyección; no acredita el código HTTP de ese fallo.
4. **Reconciliación HTTP posterior:** el cliente autenticado repite el POST con la misma acción, ámbito y `Idempotency-Key` y obtiene 200 sin duplicados, en ambos casos. El pedido del otro negocio permanece intacto.

La excepción se inyecta exclusivamente mediante un `sqlite3.Connection` de pruebas en una base temporal, y se desactiva antes del reintento. No se cambia `SqliteUnitOfWork` ni se introduce retry automático. El objetivo es comprobar el caso de **confirmación indeterminada desde la excepción del adaptador**, sin equiparar una excepción a un rollback garantizado. Faltan pruebas del contrato HTTP en la ruta inyectada, de fallos físicos y de respuesta interrumpida.

## Límites y condiciones

Se trata de una **inyección determinista de excepción**, no de una caída de máquina, fallo de fsync, corte eléctrico ni terminación de proceso durante el commit SQLite. No demuestra durabilidad ante fallos físicos, orden total distribuido ni garantías en PostgreSQL. Aunque tras inyectar el fallo la base revele uno de dos estados, el cliente real no puede deducirlo de la respuesta HTTP; debe mantener el mismo ámbito/pedido/acción/clave, consultar el estado si está autorizado y repetir con límites de intentos.

Solo desarrollo y pruebas con SQLite y datos sintéticos. CI requerida: `python -m pytest -q`, `ruff check .`, `ruff format --check .`, `mypy src` en Python 3.11 y 3.12. Pendiente revisión de PR y merge; React e identidad productiva permanecen desactivados.
