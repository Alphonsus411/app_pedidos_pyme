# Inicialización SQLite del prototipo

Para desarrollo y pruebas, crear una base nueva y dedicada con el esquema del
prototipo. La conexión pertenece al código que la abre y debe estar libre de
transacciones al inicializarla:

```python
import sqlite3
from universal_business.infrastructure.sqlite_schema import initialize_sqlite_schema

with sqlite3.connect("prototipo.db") as connection:
    initialize_sqlite_schema(connection)
    # Usar esta conexión con los adaptadores SQLite de la aplicación.
```

La operación instala las tablas e índices de ubicaciones, recursos, clientes,
reservas, disponibilidad, idempotencia y outbox; guarda la versión 1 y puede
repetirse al abrir una base compatible. Activa `foreign_keys` solo en la
conexión actual. Las claves foráneas existentes no cubren todas las relaciones
de negocio; no se debe asumir integridad referencial completa.

La base está reservada al esquema gestionado: si ya contiene objetos no
reconocidos, si la versión difiere o si el esquema ha cambiado, se rechaza sin
migrar ni modificar tablas. Para datos existentes será necesario desarrollar y
validar una migración específica. No usar esta inicialización como herramienta
de migración ni como sustituto de copias de seguridad.

El ensamblaje `SqliteReservationExecution` requiere que la frontera autentique
y autorice cada operación. La entrega de outbox necesita su worker; el fallo
entre el commit y la finalización de idempotencia aún requiere reconciliación.
El prototipo completo continúa en desarrollo.
