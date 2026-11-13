# F3.23 — Autenticación experimental de manifiestos con HMAC-SHA256

**Ámbito:** pruebas aisladas sobre respaldos SQLite sintéticos, sin secretos reales, modificación del núcleo ni despliegue.

## Contrato de laboratorio

`tests/api/test_staff_sqlite_backup_hmac.py` usa exclusivamente claves de ejemplo declaradas en el test para generar un HMAC-SHA256 sobre una representación JSON canónica (campos `algorithm`, `bytes`, `digest`, `key_id`; claves ordenadas y separadores fijos). El manifiesto contiene el MAC hexadecimal, pero **nunca el secreto**. El validador selecciona la clave de un conjunto autorizado por `key_id`, contrasta el MAC con `hmac.compare_digest` y después comprueba los bytes del archivo con el SHA-256 y el tamaño del manifiesto de F3.22.

## Cobertura

- Con manifiesto legítimo y clave vigente, se acepta un respaldo intacto.
- Rechazos: copia modificada, tamaño o digest del manifiesto adulterados, identificador de clave desconocido, MAC modificado o ausente y clave de verificación distinta. Una restauración inválida no modifica el archivo destino sintético.
- Rotación en dos fases: durante la ventana de transición las claves vieja y nueva están autorizadas; tras retirarse la clave antigua se rechaza su manifiesto, mientras el firmado con la nueva continúa válido.
- Si alguien puede cambiar el fichero y recalcular su SHA-256 sin conocer el secreto HMAC, el MAC anterior no verifica.

## Límites de seguridad

El experimento **no es una PKI, firma digital ni prueba pública de procedencia**: HMAC acredita integridad/autenticación **solo frente a un verificador que ya confía en el secreto compartido y su custodia**. Quien conozca ese secreto puede generar MAC válidos. No hay claves reales, KMS, almacén de manifiestos, gestión de expiración, ACL, auditoría de claves, recuperación entre servicios, protección contra replay de un backup antiguo correctamente autenticado, integridad frente a compromiso de claves ni garantías de durabilidad física. La comparación de archivos no sustituye la validación SQLite ni convierte un respaldo sintético en un plan de desastre productivo.

Se conserva SQLite solo en desarrollo/pruebas, sin tocar core, esquema, API, React o workflows. CI requerida en Python 3.11/3.12: pytest, Ruff y mypy. Pendiente revisión en PR antes de integrar.
