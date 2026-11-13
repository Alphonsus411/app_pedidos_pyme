# F3.25 — Checkpoint monotónico transaccional en SQLite aislado

**Alcance:** únicamente pruebas sintéticas. Este checkpoint SQLite es un segundo archivo de laboratorio y **no** constituye una fuente de confianza productiva ni un servicio externo resistente a manipulación.

## Experimento

`tests/api/test_staff_checkpoint_monotonic.py` implementa funciones locales de prueba que crean una tabla mínima `checkpoint` de una sola fila, con secuencia positiva y `backup_id` no vacío. Los cambios se realizan mediante `BEGIN IMMEDIATE` en una transacción SQLite, utilizando conexiones nuevas por operación.

- Primer checkpoint solo acepta secuencia 1.
- Una publicación sucesora solo acepta `sequence = actual + 1`; rechaza retrocesos y saltos.
- Reenviar exactamente el mismo par `(sequence, backup_id)` es idempotente.
- La misma secuencia con distinto `backup_id` se rechaza.
- La excepción sintética justo antes de confirmar la operación revierte la actualización; una nueva conexión vuelve a observar el checkpoint anterior y puede reintentarse.
- Dos hilos con conexiones independientes disputan la misma secuencia con distintos identificadores. Solo uno la publica, el otro obtiene rechazo, y queda una sola fila.
- Tras cerrar y reabrir la conexión se conserva la secuencia confirmada; se comprueba `PRAGMA integrity_check`.

## Propiedades y límites

La atomicidad y la monotonicidad se prueban **exclusivamente dentro del archivo SQLite local del laboratorio**, con bloqueo de escritor `BEGIN IMMEDIATE`. No se acredita operación distribuida, publicación atómica entre **backup y checkpoint**, `fsync`, caída de sistema operativo, seguridad contra acceso malicioso a ambos archivos ni fuente antirrollback irrevocable. Si se revierte el archivo de checkpoints junto al backup y manifiesto, la protección anterior de F3.24 deja de tener una referencia confiable. Esta tabla tampoco enlaza directamente la creación de una copia real con su publicación en el checkpoint, ni reserva números de forma duradera.

Un diseño productivo requeriría una autoridad independiente con persistencia resistente a rollback, control de permisos, coordinación transaccional y política de recuperación ante fallos parciales. Ninguno de esos requisitos se declara solucionado aquí.

SQLite continúa restringido a desarrollo y tests. No se modifica dominio, esquema de pedidos, API, React, dependencias, pipelines ni despliegues.
