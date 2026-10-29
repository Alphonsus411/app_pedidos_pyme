"""Adaptador SQLite experimental de escritura de outbox.

No configura conexiones ni migraciones y no es el adaptador PostgreSQL de
producción. El caller debe instalar el esquema y compartir la conexión con el
UnitOfWork. La codificación es explícita y debe incluir versión y datos de
ámbito; no se usa pickle ni se intenta reconstruir clases dinámicamente.
"""

import sqlite3
from collections.abc import Sequence
from typing import Protocol

from universal_business.domain.shared.events import DomainEvent


class OutboxEventEncoder(Protocol):
    """Codifica el evento completo en un formato seguro y versionado."""

    def encode(self, event: DomainEvent, /) -> bytes:
        raise NotImplementedError


def create_sqlite_outbox_schema(connection: sqlite3.Connection) -> None:
    """Crear el esquema experimental; el caller controla commit o rollback.

    Es para una base nueva de desarrollo/pruebas, no es un gestor de
    migraciones ni verifica la compatibilidad de una tabla preexistente.
    """
    connection.execute(
        """CREATE TABLE IF NOT EXISTS transactional_outbox (
            event_id TEXT PRIMARY KEY NOT NULL,
            payload BLOB NOT NULL
        )"""
    )


class SqliteOutboxWriter:
    """Inserta eventos en la transacción SQLite activa sin confirmar."""

    def __init__(self, *, connection: sqlite3.Connection, encoder: OutboxEventEncoder) -> None:
        self._connection = connection
        self._encoder = encoder

    def write_many(self, events: Sequence[DomainEvent], /) -> None:
        if not self._connection.in_transaction:
            raise RuntimeError("Outbox requiere una transacción SQLite activa")
        rows: list[tuple[str, bytes]] = []
        for event in events:
            payload = self._encoder.encode(event)
            if not isinstance(payload, bytes) or not payload:
                raise ValueError("El codificador debe devolver bytes no vacíos")
            rows.append((str(event.event_id), payload))
        self._connection.executemany(
            "INSERT INTO transactional_outbox (event_id, payload) VALUES (?, ?)", rows
        )
