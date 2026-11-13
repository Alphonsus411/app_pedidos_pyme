# F3.22 — Comprobación SHA-256 de copias SQLite (laboratorio)

**Ámbito:** exclusivamente pruebas con SQLite sintético y archivos en `tmp_path`. No se añade un servicio de respaldo ni una interfaz productiva.

## Contrato verificado

El módulo `tests/api/test_staff_sqlite_backup_digest.py` calcula un manifiesto de laboratorio con `algorithm=sha256`, longitud en bytes y resumen hexadecimal SHA-256 de un fichero de copia obtenido mediante `sqlite3.Connection.backup()`. Se utiliza el manifiesto **original, tomado como referencia confiable en el test**, para detectar ausencia del fichero, cambio de bytes, tamaño incorrecto, digest incorrecto, algoritmo no admitido o digest mal formado. Las copias intactas superan la comprobación y los tests de integridad SQLite.

**Ninguna copia inválida reemplaza un destino:** se comprueban bytes, estados de pedidos y contadores intactos en un destino sintético independiente. El validador de SHA-256 está implementado solamente en las pruebas; no toca el núcleo, el adaptador de pedidos, la API ni despliegues.

## Propiedades distintas

- **Integridad relativa:** los bytes de la copia coinciden con el resumen **de una referencia confiable**. SHA-256 no detecta cambios si el atacante puede sustituir a la vez la copia y su manifiesto.
- **Integridad SQLite:** `PRAGMA integrity_check`, `foreign_key_check` y versión de esquema verifican otras condiciones, no equivalentes a autenticidad.
- **Autenticidad de origen:** **NO demostrada**. Un manifiesto SHA-256 sin firma ni MAC no acredita autoría. La prueba muestra que, tras cambiar un fichero, el SHA anterior falla pero un digest nuevo calculado sobre los bytes cambiados coincide.
- **Durabilidad física:** no demostrada; tampoco autenticidad ante compromiso de claves, política de custodia, cifrado, retención o RPO/RTO.

La prueba de manifiestos calcula valores en memoria dentro del laboratorio; no se despliega un almacén de manifiestos. Un eventual sistema real requerirá gestión segura de claves, firma digital o HMAC con separación de permisos, inventario de backups y un procedimiento de restauración transaccional autorizado. SQLite sigue restringido a desarrollo/pruebas.
