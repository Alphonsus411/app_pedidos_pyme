# F3.19 — Integridad y persistencia SQLite tras reinicios de laboratorio

**Ámbito:** pruebas exclusivamente sintéticas sobre una base SQLite bajo `tmp_path`. No se cambian el núcleo de negocio, el esquema, la API, las políticas de autorización ni los workflows.

## Comprobaciones

La prueba parametrizada `test_sqlite_integrity_and_replay_across_process_restarts` cubre dos puntos de partida: una transacción de escritor abandonada al morir el proceso (rollback) y una transición ya confirmada con HTTP 200. En ambos casos inicia después **dos procesos Python independientes** que reconstruyen un adaptador staff de laboratorio y emiten el mismo POST de validación con idéntica clave de idempotencia.

Tras cada proceso se abre una conexión nueva y se comprueba `PRAGMA integrity_check = ok`, `PRAGMA foreign_key_check` sin infracciones y `PRAGMA user_version = 3`. Al final se exige estado persistido `validated` en el pedido, el otro pedido `draft`, y un solo incremento de filas de idempotencia y outbox. Se comprueba la ausencia de claves persistidas duplicadas y un único incremento global de idempotencia; el valor almacenado puede estar derivado de la clave HTTP y no se presume idéntico al texto proporcionado por el cliente.

Los subprocesos usan únicamente el worker sintético F3.16, con códigos de salida controlados; las sesiones opacas son nuevas por proceso, sin compartir memoria. No se reinicia ni detiene ningún servicio externo.

## Qué demuestran y qué no

Las verificaciones son **integridad lógica y recuperación entre procesos con terminación ordenada del caso postcommit**, no durabilidad ante corte eléctrico ni caída de hardware/OS, corrupción de disco, saturación, red, copias de seguridad, o recuperación entre máquinas. `PRAGMA integrity_check` no equivale a una garantía de fsync ni prueba todas las invariantes de negocio. `foreign_key_check` se comprueba explícitamente en nuevas conexiones; SQLite solo está permitido en desarrollo y tests.

No se habilita el panel staff ni identidad productiva. La tolerancia a commits inciertos de F3.17/F3.18 sigue limitada a excepciones sintéticas. Ejecutar pytest, Ruff y mypy en Python 3.11/3.12 antes de proponer merge.
