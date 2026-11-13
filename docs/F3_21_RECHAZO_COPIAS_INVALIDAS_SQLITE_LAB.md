# F3.21 — Rechazo de copias SQLite dañadas o incompatibles (laboratorio)

**Ámbito:** exclusivamente pruebas sintéticas. No se proporciona una herramienta de restauración para producción y no se interviene en despliegues, esquema, núcleo de negocio, API, clientes o workflows.

## Contrato de laboratorio

El módulo `tests/api/test_staff_sqlite_backup_rejection.py` incluye un **helper exclusivo de tests** que valida la copia candidata antes de cualquier sustitución del destino. Abre el archivo candidato en modo solo lectura (`mode=ro`, sin crear archivos ausentes), comprueba `PRAGMA integrity_check`, `PRAGMA foreign_key_check`, `user_version=3` y la presencia mínima de las tablas `orders`, `idempotency` y `transactional_outbox`.

Para una candidata aceptada se crea una ubicación temporal bajo el mismo directorio de destino, se hace una copia mediante `sqlite3.Connection.backup()`, se vuelve a validar y solo entonces se invoca `os.replace()` para el archivo sintético de destino. Un `finally` limpia el archivo temporal. Esto es un **patrón de ensayo**, no una rutina apta para reemplazar una BD abierta o desplegada.

## Casuística

Se comprueba el rechazo de candidatas **inexistentes, vacías, con cabecera incorrecta, truncadas, con esquema ausente o versión de esquema incompatible**. Para cada caso se exige excepción, destino original idéntico en bytes, integridad y estado de pedidos intactos, contadores sin cambios y ausencia de ficheros temporales residuales. Un caso positivo cubre restauración de candidata válida en un archivo sintético aislado.

## Límites

`PRAGMA integrity_check` y la comprobación mínima de tablas no certifican todas las reglas del dominio; una copia alterada pero coherente podría superar esas comprobaciones. No existe validación criptográfica/autenticidad, gestión de copias cifradas, retención, procedencia, ACL, política de migraciones, recuperación multiarchivo ni coordinación con procesos en producción. `os.replace()` en este test no asegura por sí solo durabilidad ante fallos físicos ni es apropiado para una base en servicio. Mantener SQLite solo en desarrollo y pruebas.

**Validación:** pytest, Ruff y mypy sobre Python 3.11 y 3.12. Revisión de PR antes de fusionar.
