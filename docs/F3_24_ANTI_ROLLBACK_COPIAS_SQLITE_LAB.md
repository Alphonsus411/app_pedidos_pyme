# F3.24 — Protección contra restauración de respaldos antiguos (laboratorio)

**Ámbito:** pruebas con datos sintéticos, SQLite exclusivamente para desarrollo y tests. No se incorpora infraestructura de producción, claves reales ni lógica en el dominio.

## Problema

Un respaldo SQLite antiguo puede conservar un HMAC-SHA256 perfectamente válido. Por tanto, autenticidad e integridad de bytes **no implican actualidad**. La decisión de aceptar una restauración requiere un punto de control independiente del respaldo y del manifiesto.

## Experimento

El archivo `tests/api/test_staff_sqlite_backup_hmac.py` ensaya un identificador de respaldo (`backup_id`) y una secuencia positiva (`sequence`) incluidos en los campos autenticados del manifiesto HMAC. Se utiliza serialización JSON canónica y comparación `hmac.compare_digest`, y después se comprueba el SHA-256 y tamaño del archivo.

Se construyen dos copias sintéticas: la primera antes de validar un pedido y la segunda después. Ambas poseen HMAC correctos. El validador de laboratorio recibe por **parámetros separados** un checkpoint confiable externo (`trusted_sequence`, `trusted_backup_id`) y rechaza la copia más antigua cuando el checkpoint autorizado señala la más reciente. Además, prueba que una secuencia alterada, un identificador alterado o uno diferente pero correctamente firmado para la misma secuencia no se aceptan. Sin checkpoint externo disponible, el validador falla de forma cerrada. El destino y los datos originales permanecen intactos.

**La implementación solo compara con el checkpoint suministrado**: no persiste ni actualiza un contador monotónico, ni ofrece una operación atómica de reserva/publicación de secuencia. El checkpoint del test no es un registro resistente a manipulación.

## Condiciones y límites

La secuencia debe ser asignada y custodiada por una autoridad independiente del almacenamiento de copias. Si un adversario puede revertir simultáneamente backup, manifiesto **y checkpoint**, este laboratorio no detecta el ataque. Tampoco existe protección contra compromiso de clave HMAC, restauración deliberada autorizada de estados antiguos, concurrencia de escritores, caducidad, recuperación multi-sistema, borrado de versiones, ni sistema productivo de claves.

SQLite se mantiene solo en desarrollo/pruebas; sin cambios de core, API, esquema, React, workflows o despliegues. Se requiere CI de Python 3.11/3.12 con pytest, Ruff y mypy antes de revisión/integración.
