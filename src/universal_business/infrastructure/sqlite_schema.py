"""Inicialización y comprobación estricta del esquema SQLite del prototipo."""

import sqlite3

from universal_business.infrastructure.sqlite_availability import create_sqlite_availability_schema
from universal_business.infrastructure.sqlite_customers import create_sqlite_customers_schema
from universal_business.infrastructure.sqlite_idempotency import create_sqlite_idempotency_schema
from universal_business.infrastructure.sqlite_locations import create_sqlite_locations_schema
from universal_business.infrastructure.sqlite_offerings import create_sqlite_offerings_schema
from universal_business.infrastructure.sqlite_orders import create_sqlite_orders_schema
from universal_business.infrastructure.sqlite_outbox import (
    create_sqlite_delivery_schema,
    create_sqlite_outbox_schema,
)
from universal_business.infrastructure.sqlite_reservations import create_sqlite_reservations_schema
from universal_business.infrastructure.sqlite_resources import create_sqlite_resources_schema
from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork

SCHEMA_VERSION = 3


class IncompatibleSqliteSchemaError(RuntimeError):
    """La base no es nueva ni coincide con el esquema gestionado conocido."""


def _create_schema(connection: sqlite3.Connection) -> None:
    create_sqlite_locations_schema(connection)
    create_sqlite_resources_schema(connection)
    create_sqlite_customers_schema(connection)
    create_sqlite_reservations_schema(connection)
    create_sqlite_availability_schema(connection)
    create_sqlite_idempotency_schema(connection)
    create_sqlite_outbox_schema(connection)
    create_sqlite_delivery_schema(connection)


def _objects(connection: sqlite3.Connection) -> tuple[tuple[object, ...], ...]:
    rows = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    )
    return tuple(tuple(row) for row in rows)


def _expected_objects(version: int = SCHEMA_VERSION) -> tuple[tuple[object, ...], ...]:
    with sqlite3.connect(":memory:") as connection:
        _create_schema(connection)
        if version not in (1, 2, 3):
            raise ValueError("Versión de esquema desconocida")
        if version >= 2:
            create_sqlite_orders_schema(connection)
        if version >= 3:
            create_sqlite_offerings_schema(connection)
        return _objects(connection)


def initialize_sqlite_schema(connection: sqlite3.Connection) -> None:
    """Inicializar una base vacía o validar una base gestionada versión 3.

    Se exige propiedad exclusiva del esquema: tablas, índices, vistas y triggers
    adicionales se rechazan. No migra ni adopta bases legacy, no cierra la
    conexión y no instala datos de ejemplo. La comprobación y creación se hacen
    bajo BEGIN IMMEDIATE; cualquier fallo revierte el esquema y su versión.
    Activa claves foráneas para esta conexión, no para otras conexiones.
    """
    if connection.in_transaction:
        raise RuntimeError("Se requiere una conexión sin transacción activa")
    if getattr(connection, "autocommit", None) is True:
        raise RuntimeError("autocommit=True no es compatible con esta UoW")
    connection.execute("PRAGMA foreign_keys=ON")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise RuntimeError("No se pudieron activar las claves foráneas")
    expected = _expected_objects()
    with SqliteUnitOfWork(connection) as uow:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        actual = _objects(connection)
        if version == 0 and not actual:
            _create_schema(connection)
            create_sqlite_orders_schema(connection)
            create_sqlite_offerings_schema(connection)
            if _objects(connection) != expected:
                raise IncompatibleSqliteSchemaError("Esquema inicial incoherente")
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        elif version != SCHEMA_VERSION or actual != expected:
            raise IncompatibleSqliteSchemaError("Esquema SQLite no compatible; no se ha migrado")
        uow.commit()


def migrate_sqlite_v1_to_v2(connection: sqlite3.Connection) -> None:
    """Migrar solo esquema v1 íntegro a v2, en una transacción explícita.

    El llamador debe hacer una copia de seguridad verificable previamente.
    Nunca adopta un esquema modificado ni tablas de pedidos preexistentes.
    Ejecutar con conexión sin transacción y sin otros cambios manuales.
    """
    if connection.in_transaction:
        raise RuntimeError("Se requiere una conexión sin transacción activa")
    if getattr(connection, "autocommit", None) is True:
        raise RuntimeError("autocommit=True no es compatible con esta UoW")
    connection.execute("PRAGMA foreign_keys=ON")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise RuntimeError("No se pudieron activar las claves foráneas")
    v1, v2 = _expected_objects(1), _expected_objects(2)
    with SqliteUnitOfWork(connection) as uow:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        current = _objects(connection)
        if version == 2 and current == v2:
            uow.commit()
            return
        if version != 1 or current != v1:
            raise IncompatibleSqliteSchemaError("Esquema v1 no compatible; no se ha migrado")
        create_sqlite_orders_schema(connection)
        if _objects(connection) != v2:
            raise IncompatibleSqliteSchemaError("Esquema v2 incoherente; no se ha migrado")
        connection.execute("PRAGMA user_version=2")
        uow.commit()


def migrate_sqlite_v2_to_v3(connection: sqlite3.Connection) -> None:
    """Migrar una base gestionada v2 íntegra a v3 de forma explícita.

    El caller debe verificar una copia de seguridad antes de migrar. No se
    adoptan ofertas instaladas por separado ni esquemas alterados.
    """
    if connection.in_transaction:
        raise RuntimeError("Se requiere una conexión sin transacción activa")
    if getattr(connection, "autocommit", None) is True:
        raise RuntimeError("autocommit=True no es compatible con esta UoW")
    connection.execute("PRAGMA foreign_keys=ON")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise RuntimeError("No se pudieron activar las claves foráneas")
    v2, v3 = _expected_objects(2), _expected_objects(3)
    with SqliteUnitOfWork(connection) as uow:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        current = _objects(connection)
        if version == 3 and current == v3:
            uow.commit()
            return
        if version != 2 or current != v2:
            raise IncompatibleSqliteSchemaError("Esquema v2 no compatible; no se ha migrado")
        create_sqlite_offerings_schema(connection)
        if _objects(connection) != v3:
            raise IncompatibleSqliteSchemaError("Esquema v3 incoherente; no se ha migrado")
        connection.execute("PRAGMA user_version=3")
        uow.commit()
