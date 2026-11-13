# F3.27 — Reconciliación de copias con manifiesto autenticado (laboratorio)

**Alcance:** exclusivamente pruebas sintéticas y clasificación de estado de copias SQLite temporales. El núcleo, la API, los paneles, los contratos, el esquema de pedidos y los workflows no cambian.

## Objetivo y evidencia

F3.26 clasificaba copias por presencia del archivo, `PRAGMA integrity_check`, intención y checkpoint; esa combinación no acreditaba que el archivo correspondiera a la identidad indicada. F3.27 agrega `tests/api/test_staff_backup_authenticated_reconciliation.py` con un observador de pruebas **solo lectura** que exige dos condiciones distintas antes de devolver `confirmed_authenticated`:

1. La intención está confirmada y el checkpoint coincide con `sequence` y `backup_id` (`_observe` de F3.26).
2. El manifiesto firmado mediante HMAC-SHA256 vincula criptográficamente el contenido exacto de la copia y su identidad/secuencia con el checkpoint (`_verify_latest` de F3.24, con SHA-256 y tamaño de F3.22).

Los tests incluyen un respaldo correcto, ausencia de manifiesto, cambio de identidad o secuencia con firma correcta pero checkpoint incompatible, MAC modificado, modificación posterior del fichero, sustitución por **otra base SQLite íntegra pero distinta**, y casos con intención pendiente aunque el manifiesto sea auténtico. Una copia válida no puede confirmar por sí sola una intención pendiente. El estado del checkpoint y del registro de intenciones permanece inalterado y un archivo destino ajeno no se sobrescribe.

## Límites

HMAC acredita posesión de una clave compartida sintética del test, **no autoría pública ni procedencia independiente**. Tampoco sustituye una autoridad monotónica externa resistente a rollback, la coordinación transaccional entre intención, backup y checkpoint, ni una política de auditoría o reparación. El observador exige que los artefactos sean legibles y la identidad coincida, pero no repara, elimina, promueve ni restaura. No simula ataques con compromiso de la clave ni cortes eléctricos. Los archivos son temporales, sin datos reales ni despliegue.

**Gate de integración:** pruebas completas y Ruff/Mypy en Python 3.11 y 3.12, revisión del diff y PR antes de actualizar `master`.
