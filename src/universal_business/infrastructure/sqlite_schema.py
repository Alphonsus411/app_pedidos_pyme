"""Inicialización y comprobación estricta del esquema SQLite del prototipo."""

import sqlite3

from universal_business.infrastructure.sqlite_availability import create_sqlite_availability_schema
from universal_business.infrastructure.sqlite_customers import create_sqlite_customers_schema
from universal_business.infrastructure.sqlite_idempotency import create_sqlite_idempotency_schema
from universal_business.infrastructure.sqlite_locations import create_sqlite_locations_schema
from universal_business.infrastructure.sqlite_outbox import (
    create_sqlite_delivery_schema,
    create_sqlite_outbox_schema,
)
from universal_business.infrastructure.sqlite_reservations import create_sqlite_reservations_schema
from universal_business.infrastructure.sqlite_resources import create_sqlite_resources_schema
from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork

SCHEMA_VERSION = 1


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


def _expected_objects() -> tuple[tuple[object, ...], ...]:
    with sqlite3.connect(":memory:") as connection:
        _create_schema(connection)
        return _objects(connection)


def initialize_sqlite_schema(connection: sqlite3.Connection) -> None:
    """Inicializar una base vacía o validar una base gestionada versión 1.

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
            if _objects(connection) != expected:
                raise IncompatibleSqliteSchemaError("Esquema inicial incoherente")
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        elif version != SCHEMA_VERSION or actual != expected:
            raise IncompatibleSqliteSchemaError("Esquema SQLite no compatible; no se ha migrado")
        uow.commit()
