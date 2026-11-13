# F3.20 — Copia y restauración SQLite verificadas (laboratorio)

**Estado:** pruebas automatizadas sintéticas en rama independiente. SQLite únicamente desarrollo/pruebas. No representa un mecanismo de respaldo desplegable.

## Método

La regresión `tests/api/test_staff_sqlite_backup_restore.py::test_backup_restore_replay` compara dos instantáneas: una tomada **antes** de confirmar la transición de un pedido y otra **después**. Utiliza la API `sqlite3.Connection.backup()` para capturar el origen en un archivo temporal independiente, en vez de copiar directamente un fichero SQLite que podría tener operaciones en curso.

Después de la copia, la base de origen continúa aceptando transiciones de los pedidos de dos negocios. Una segunda operación de backup restaura la instantánea en **otro archivo**, sin sobrescribir la base original ni reintroducir sus cambios posteriores.

Cada copia/restauración comprueba desde nuevas conexiones:

- `PRAGMA integrity_check` devuelve únicamente `ok`.
- `PRAGMA foreign_key_check` no informa infracciones.
- `PRAGMA user_version` sigue siendo 3.
- Estado del pedido principal acorde a la fecha lógica del backup; pedido del otro negocio permanece `draft` en la restauración.
- Contadores de idempotencia y outbox permanecen en la foto temporal correcta.

Se inician **dos procesos Python independientes** tras restaurar; cada uno reconstruye el adaptador staff de laboratorio, emite el mismo POST con idéntica clave idempotente y termina con código controlado. Tras ambos replays, la copia restaurada contiene un único incremento de idempotencia y outbox. La base original conserva los dos pedidos confirmados sin verse afectada por la restauración.

## Límites y riesgos pendientes

Esta evidencia demuestra restauración lógica y coherencia de una instantánea obtenida mediante el respaldo online SQLite en archivos temporales. **No demuestra** almacenamiento externo o redundante, recuperación de desastre real, cifrado de copias, conservación/retención, consistencia de otros servicios, durabilidad física, fsync, recuperación de discos dañados, RPO/RTO ni una política productiva de backup. No emplear copias de ficheros abiertos como sustituto de la API SQLite de respaldo; tampoco asumir que `integrity_check` comprueba todas las invariantes de negocio.

Ninguna rama activa el panel staff, cambia el núcleo universal, el esquema, el frontend o los workflows. Se utilizan exclusivamente pedidos sintéticos. Pendiente revisión e integración tras CI verde en Python 3.11 y 3.12 con pytest, Ruff y mypy.
