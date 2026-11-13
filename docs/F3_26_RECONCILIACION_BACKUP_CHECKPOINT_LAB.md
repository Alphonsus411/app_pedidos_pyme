# F3.26 — Reconciliación de fallos entre backup y checkpoint (laboratorio)

**Estado:** prueba sintética de ventanas de fallo entre dos ficheros SQLite independientes. Ningún cambio del núcleo de pedidos, esquema productivo, API, frontend, workflows o despliegues.

## Modelo experimental

`tests/api/test_staff_backup_checkpoint_windows.py` define un registro de intención de respaldo en un fichero de pruebas separado, una copia sintética de una tabla de pedidos y un segundo fichero de prueba que actúa como checkpoint monotónico (aprovechando las funciones aisladas de F3.25).

El flujo se inspecciona con conexiones nuevas en cuatro puntos distintos:

1. **Pendiente sin copia**: la intención existe, pero el artefacto no. Se clasifica `missing_artifact`.
2. **Copia generada, checkpoint no publicado**: la intención y la copia existen; la operación se clasifica `pending_unpublished` y no se asume confirmación.
3. **Checkpoint publicado, intención todavía pendiente**: se clasifica `published_not_finalized`. Reenviar el mismo checkpoint es idempotente; uno diferente con la misma secuencia se rechaza.
4. **Confirmado**: la intención figura `confirmed`, el artefacto existe e identifica la copia y el checkpoint coincide.

Se añaden casos de **copia huérfana** sin intención, eliminación de artefacto después de confirmar, copia inválida, identificador contradictorio y una excepción inyectada antes del commit del checkpoint. La operación fallida permanece pendiente hasta una acción explícita; el observador de estado es de **solo lectura** y no elimina, promueve ni reemplaza nada.

## Interpretación y garantías

Estos tests comprueban la **clasificación conservadora** de estados y la continuidad de un checkpoint SQLite local. No hay transacción atómica entre el fichero de copia, la intención y el checkpoint; son tres unidades de persistencia distintas. El experimento no dispone de almacenamiento de confianza resistente a rollback, de ordenación distribuida, de control de concurrencia entre múltiples creadores de copias ni de recuperación automática autorizada.

La validación de integridad sintética mediante `PRAGMA integrity_check` **no autentica el origen** ni vincula criptográficamente la copia con el `backup_id`: esos límites se estudian en F3.22–F3.24. Ningún resultado constituye un protocolo de restauración seguro en producción, ni acredita fallos de hardware, cortes eléctricos o durabilidad física.

SQLite permanece exclusivamente en desarrollo y pruebas, con artefactos `tmp_path`. Pendientes de diseño futuro: conciliación real entre artefactos y manifiestos firmados, procedencia del checkpoint, caducidad de intenciones y reparación manual auditada, siempre sin exponer datos productivos.
