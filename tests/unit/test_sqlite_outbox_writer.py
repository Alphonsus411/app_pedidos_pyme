"""Pruebas del adaptador experimental con dos conexiones SQLite."""

import sqlite3
from pathlib import Path
from types import TracebackType
from unittest.mock import Mock

import pytest

from universal_business.application.execution import execute_use_case
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import OrderId
from universal_business.infrastructure.sqlite_outbox import (
    SqliteOutboxWriter,
    create_sqlite_outbox_schema,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "outbox.db"
    with sqlite3.connect(path) as connection:
        create_sqlite_outbox_schema(connection)
        connection.execute("CREATE TABLE orders (id TEXT PRIMARY KEY)")
    return path


@pytest.fixture
def event() -> DomainEvent:
    return DomainEvent(aggregate_id=OrderId.generate(), aggregate_type="Order")


def test_writer_commits_with_business_state(db_path: Path, event: DomainEvent) -> None:
    encoder = Mock()
    encoder.encode.return_value = b'{"version":1}'
    with sqlite3.connect(db_path) as connection:
        connection.execute("BEGIN")
        connection.execute("INSERT INTO orders VALUES ('order-1')")
        SqliteOutboxWriter(connection=connection, encoder=encoder).write_many([event])
        with sqlite3.connect(db_path) as reader:
            assert reader.execute("SELECT count(*) FROM transactional_outbox").fetchone() == (0,)
    with sqlite3.connect(db_path) as reader:
        assert reader.execute("SELECT id FROM orders").fetchall() == [("order-1",)]
        assert reader.execute("SELECT event_id, payload FROM transactional_outbox").fetchall() == [
            (str(event.event_id), b'{"version":1}')
        ]
    encoder.encode.assert_called_once_with(event)


def test_duplicate_id_aborts_transaction_when_caller_rolls_back(
    db_path: Path, event: DomainEvent
) -> None:
    encoder = Mock()
    encoder.encode.return_value = b"event"
    with pytest.raises(sqlite3.IntegrityError):
        with sqlite3.connect(db_path) as connection:
            connection.execute("BEGIN")
            connection.execute("INSERT INTO orders VALUES ('order-1')")
            SqliteOutboxWriter(connection=connection, encoder=encoder).write_many([event, event])
    with sqlite3.connect(db_path) as reader:
        assert reader.execute("SELECT * FROM orders").fetchall() == []
        assert reader.execute("SELECT * FROM transactional_outbox").fetchall() == []


@pytest.mark.parametrize("payload", [b"", "not bytes", None])
def test_invalid_encoding_does_not_write_partial_batch(
    db_path: Path, event: DomainEvent, payload: object
) -> None:
    other = DomainEvent(aggregate_id=OrderId.generate(), aggregate_type="Order")
    encoder = Mock()
    encoder.encode.side_effect = [b"valid", payload]
    with sqlite3.connect(db_path) as connection:
        connection.execute("BEGIN")
        with pytest.raises(ValueError, match="bytes no vacíos"):
            SqliteOutboxWriter(connection=connection, encoder=encoder).write_many([event, other])
        assert connection.execute("SELECT * FROM transactional_outbox").fetchall() == []


def test_writer_requires_active_transaction(db_path: Path, event: DomainEvent) -> None:
    encoder = Mock()
    with sqlite3.connect(db_path) as connection:
        with pytest.raises(RuntimeError, match="transacción SQLite activa"):
            SqliteOutboxWriter(connection=connection, encoder=encoder).write_many([event])
    encoder.encode.assert_not_called()


def test_orchestrator_and_writer_commit_together(db_path: Path, event: DomainEvent) -> None:
    connection = sqlite3.connect(db_path)

    class Uow:
        committed = False

        def __enter__(self) -> "Uow":
            connection.execute("BEGIN")
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> None:
            if not self.committed:
                connection.rollback()

        def commit(self) -> None:
            connection.commit()
            self.committed = True

        def rollback(self) -> None:
            connection.rollback()

    class Handler:
        def handle(self, value: str) -> tuple[str, list[DomainEvent]]:
            connection.execute("INSERT INTO orders VALUES (?)", (value,))
            return value, [event]

    encoder = Mock()
    encoder.encode.return_value = b"versioned-payload"
    publisher = Mock()
    try:
        assert (
            execute_use_case(
                handler=Handler(),
                input="order-1",
                unit_of_work=Uow(),
                event_dispatcher=Mock(),
                event_publisher=publisher,
                outbox_writer=SqliteOutboxWriter(connection=connection, encoder=encoder),
            )
            == "order-1"
        )
        with sqlite3.connect(db_path) as reader:
            assert reader.execute("SELECT id FROM orders").fetchall() == [("order-1",)]
            assert reader.execute(
                "SELECT event_id, payload FROM transactional_outbox"
            ).fetchall() == [(str(event.event_id), b"versioned-payload")]
        publisher.publish_many.assert_not_called()
    finally:
        connection.close()
