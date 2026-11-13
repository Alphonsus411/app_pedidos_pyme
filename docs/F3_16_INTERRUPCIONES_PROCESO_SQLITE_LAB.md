# F3.16 — Interrupción de procesos y límites del commit SQLite (laboratorio)

**Alcance:** pruebas de regresión con un proceso Python independiente, sobre una base SQLite temporal y exclusivamente sintética. No se modifica el núcleo, la API, el esquema ni los workflows. La transacción real de producción no se considera validada.

## Escenarios reproducibles

- **Antes del commit:** el subproceso abre una conexión SQLite independiente, adquiere `BEGIN IMMEDIATE`, modifica temporalmente el estado de un pedido sintético y termina mediante `os._exit(17)` sin commit ni rollback explícito. Un proceso posterior comprueba que SQLite deshizo la escritura, que idempotencia y outbox permanecen iguales y que el pedido del otro negocio está intacto. A continuación un POST staff autenticado con clave fija cambia el pedido exactamente una vez.
- **Después del commit:** otro subproceso compone el adaptador staff de laboratorio completo, crea su propia sesión opaca de servidor y ejecuta un POST real contra FastAPI + SQLite. Verificado el HTTP 200 **dentro del subproceso**, termina mediante `os._exit(18)` sin entregar la respuesta al proceso padre. El padre comprueba el estado y los contadores de la base usando conexiones nuevas. Su POST con la misma clave idempotente y su propia sesión autorizada recupera 200 sin duplicar idempotencia/outbox.

Las terminaciones intencionales se ejecutan **solo** en subprocesos y con un archivo bajo `tmp_path`; se comprueban códigos de salida exactos y se impone timeout al proceso. No se envían señales al servidor real ni a otros servicios.

## Interpretación honesta

El escenario previo al commit **no** termina el handler de dominio en mitad de su ejecución: simula la muerte de un escritor SQLite con transacción sin confirmar. El escenario posterior **no** interrumpe el propio commit: el cliente padre simplemente no recibe el resultado exitoso del subproceso. Por tanto, estas pruebas delimitan las dos fronteras conocidas, pero **no resuelven** el caso de muerte durante `sqlite3.Connection.commit()`, fallo de fsync, caída del sistema operativo ni pérdidas de alimentación.

No se permite concluir a partir de estos casos que se ha obtenido exactly-once distribuido, tolerancia a fallos físicos o garantía de durabilidad completa. Ante un resultado de commit incierto, se requiere consulta autorizada si hay permiso, reintento con idéntica clave, sin cambio de alcance ni acción, y protocolo conservador de reconciliación descrito en F3.15.

## Validación y siguientes riesgos

`python -m pytest -q tests/api/test_staff_order_transitions.py`, `ruff check .`, `ruff format --check .`, `mypy src` y CI Python 3.11/3.12. Sigue pendiente validar caídas reales dentro de la transacción UoW, múltiples procesos concurrentes sostenidos, política comercial e identidad productiva. La composición normal de React permanece desactivada; SQLite exclusivamente para desarrollo y pruebas.
