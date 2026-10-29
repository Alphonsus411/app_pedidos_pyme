"""Adaptador SQLite experimental de escritura de outbox.

No configura conexiones ni migraciones y no es el adaptador PostgreSQL de
producción. El caller debe instalar el esquema y compartir la conexión con el
UnitOfWork. La codificación es explícita y debe incluir versión y datos de
ámbito; no se usa pickle ni se intenta reconstruir clases dinámicamente.
"""

import sqlite3
import time
from collections.abc import Callable, Sequence
from math import isfinite
from secrets import token_urlsafe
from typing import Protocol

from universal_business.application.events.outbox_delivery import ClaimedOutboxEvent
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import DomainEventId


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


class OutboxEventDecoder(Protocol):
    """Reconstruye un evento completo desde un formato explícito y versionado."""

    def decode(self, payload: bytes, /) -> DomainEvent:
        raise NotImplementedError


def create_sqlite_delivery_schema(connection: sqlite3.Connection) -> None:
    """Crear tabla experimental de adjudicaciones para una base nueva."""
    connection.execute(
        """CREATE TABLE IF NOT EXISTS outbox_delivery (
            event_id TEXT PRIMARY KEY NOT NULL,
            token TEXT,
            expires_at REAL,
            delivered INTEGER NOT NULL DEFAULT 0 CHECK (delivered IN (0, 1)),
            FOREIGN KEY (event_id) REFERENCES transactional_outbox(event_id)
        )"""
    )


class LostOutboxClaimError(RuntimeError):
    """La adjudicación ya no pertenece al proceso o ha caducado."""


class SqliteOutboxDeliveryStore:
    """Adjudicación SQLite experimental: una conexión nueva por operación.

    No es un adaptador de producción: no aporta aislamiento de tenants,
    migraciones, cuarentena de eventos inválidos ni planificación. El reloj
    debe ser consistente entre procesos que compartan la base. Los bloqueos
    y contención de SQLite no representan el comportamiento de PostgreSQL.
    """

    def __init__(
        self,
        *,
        connect: Callable[[], sqlite3.Connection],
        decoder: OutboxEventDecoder,
        lease_seconds: float,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not isfinite(lease_seconds) or lease_seconds <= 0:
            raise ValueError("La duración de adjudicación debe ser finita y positiva")
        self._connect = connect
        self._decoder = decoder
        self._lease_seconds = lease_seconds
        self._clock = clock

    def _now(self) -> float:
        now = self._clock()
        if not isfinite(now) or not isfinite(now + self._lease_seconds):
            raise ValueError("Reloj de adjudicación inválido")
        return now

    def claim_one(self) -> ClaimedOutboxEvent | None:
        connection = self._connect()
        try:
            if connection.in_transaction:
                raise RuntimeError("Se requiere una conexión nueva sin transacción")
            connection.execute("BEGIN IMMEDIATE")
            now = self._now()
            row = connection.execute(
                """SELECT o.event_id, o.payload FROM transactional_outbox AS o
                   LEFT JOIN outbox_delivery AS d ON d.event_id = o.event_id
                   WHERE d.event_id IS NULL OR (d.delivered = 0 AND d.expires_at <= ?)
                   ORDER BY o.rowid LIMIT 1""",
                (now,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            event = self._decoder.decode(row[1])
            if not isinstance(event, DomainEvent) or str(event.event_id) != row[0]:
                raise ValueError("El evento decodificado no coincide con su identificador")
            token = token_urlsafe(32)
            connection.execute(
                """INSERT INTO outbox_delivery (event_id, token, expires_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(event_id) DO UPDATE SET token = excluded.token,
                     expires_at = excluded.expires_at""",
                (row[0], token, now + self._lease_seconds),
            )
            connection.commit()
            return ClaimedOutboxEvent(event=event, claim_token=token)
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def mark_delivered(self, event_id: DomainEventId, claim_token: str, /) -> None:
        connection = self._connect()
        try:
            if connection.in_transaction:
                raise RuntimeError("Se requiere una conexión nueva sin transacción")
            connection.execute("BEGIN IMMEDIATE")
            result = connection.execute(
                """UPDATE outbox_delivery SET delivered = 1, token = NULL, expires_at = NULL
                   WHERE event_id = ? AND token = ? AND delivered = 0 AND expires_at > ?""",
                (str(event_id), claim_token, self._now()),
            )
            if result.rowcount != 1:
                raise LostOutboxClaimError("Adjudicación ausente, ajena o caducada")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
