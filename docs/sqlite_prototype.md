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
reservas, pedidos, ofertas, disponibilidad, idempotencia y outbox; guarda la
versión 3 y puede
repetirse al abrir una base compatible. Activa `foreign_keys` solo en la
conexión actual. Las claves foráneas existentes no cubren todas las relaciones
de negocio; no se debe asumir integridad referencial completa.

La base está reservada al esquema gestionado: si ya contiene objetos no
reconocidos, si la versión difiere o si el esquema ha cambiado, se rechaza sin
migrar ni modificar tablas. Para datos existentes fuera de los esquemas gestionados será necesario
desarrollar y validar una migración específica. No usar esta inicialización como herramienta
de migración ni como sustituto de copias de seguridad.

El ensamblaje `SqliteReservationExecution` requiere que la frontera autentique
y autorice cada operación. La entrega de outbox necesita su worker. En ese
ensamblaje, resultado de idempotencia y cambios se confirman juntos; registros
RESERVED de ejecuciones anteriores siguen requiriendo reconciliación manual.
Otros usos del almacén mantienen su modalidad previa de complete postcommit.
El prototipo completo continúa en desarrollo.

## Migración de una base gestionada v1

El inicializador no migra automáticamente. Antes de migrar, detener los
usuarios de la base y realizar y comprobar una copia de seguridad. Ejecutar
explícitamente `migrate_sqlite_v1_to_v2(connection)` con la conexión sin
transacción. A continuación ejecutar la migración v2 a v3 antes de llamar a
`initialize_sqlite_schema(connection)`.
La migración agrega la tabla e índices de pedidos de forma transaccional y
conserva los datos de v1. Solo acepta el esquema v1 íntegro o una v2 íntegra ya
migrada; rechaza cambios o tablas adicionales, incluidas tablas de pedidos
creadas por separado. No migra bases legacy sin versión ni esquemas alterados.

## Migración de una base gestionada v2

Tras detener los usuarios y verificar una copia de seguridad, ejecutar
`migrate_sqlite_v2_to_v3(connection)` con una conexión sin transacción. Añade
ofertas e índices dentro de una transacción y conserva los datos existentes.
La función acepta v2 íntegra o v3 íntegra ya migrada; rechaza esquemas
alterados o tablas de ofertas instaladas por separado, sin adoptar sus datos.
Después se puede llamar a `initialize_sqlite_schema(connection)`.
