"""Pruebas de frontera transaccional con SQLite; no validan PostgreSQL."""

import sqlite3
from collections.abc import Sequence
from pathlib import Path
from types import TracebackType
from unittest.mock import Mock

import pytest

from universal_business.application.execution import ExecutionHooks, execute_use_case
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import OrderId


class SqliteUow:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.committed = False

    def __enter__(self) -> "SqliteUow":
        self.connection.execute("BEGIN")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if not self.committed:
            self.connection.rollback()

    def commit(self) -> None:
        self.connection.commit()
        self.committed = True

    def rollback(self) -> None:
        self.connection.rollback()


class Handler:
    def __init__(self, connection: sqlite3.Connection, event: DomainEvent) -> None:
        self.connection = connection
        self.event = event
        self.failure = Mock()

    def handle(self, value: str) -> tuple[str, Sequence[DomainEvent]]:
        self.connection.execute("INSERT INTO orders (id) VALUES (?)", (value,))
        return value, [self.event]

    def build_hooks(self, value: str, result: str) -> ExecutionHooks[str]:
        return ExecutionHooks(on_failure=self.failure)


class Outbox:
    def __init__(self, connection: sqlite3.Connection, fail: bool = False) -> None:
        self.connection = connection
        self.fail = fail

    def write_many(self, events: Sequence[DomainEvent], /) -> None:
        for event in events:
            self.connection.execute(
                "INSERT INTO outbox (event_id) VALUES (?)", (str(event.event_id),)
            )
        if self.fail:
            raise RuntimeError("outbox write failed")


@pytest.mark.parametrize("fail", [False, True])
def test_outbox_and_domain_share_real_transaction(tmp_path: Path, fail: bool) -> None:
    db = str(tmp_path / "outbox.sqlite")
    with sqlite3.connect(db) as setup:
        setup.execute("CREATE TABLE orders (id TEXT PRIMARY KEY)")
        setup.execute("CREATE TABLE outbox (event_id TEXT PRIMARY KEY)")
    connection = sqlite3.connect(db)
    event = DomainEvent(aggregate_id=OrderId.generate(), aggregate_type="Order")
    handler = Handler(connection, event)
    dispatcher, publisher = Mock(), Mock()
    args = dict(
        handler=handler,
        input="order-1",
        unit_of_work=SqliteUow(connection),
        event_dispatcher=dispatcher,
        event_publisher=publisher,
        outbox_writer=Outbox(connection, fail=fail),
    )
    try:
        if fail:
            with pytest.raises(RuntimeError, match="outbox write failed"):
                execute_use_case(**args)
        else:
            assert execute_use_case(**args) == "order-1"
        with sqlite3.connect(db) as reader:
            orders = reader.execute("SELECT id FROM orders").fetchall()
            outbox = reader.execute("SELECT event_id FROM outbox").fetchall()
        if fail:
            assert orders == outbox == []
            handler.failure.assert_called_once()
            dispatcher.dispatch_many.assert_not_called()
        else:
            assert orders == [("order-1",)]
            assert outbox == [(str(event.event_id),)]
            handler.failure.assert_not_called()
            dispatcher.dispatch_many.assert_called_once_with([event])
        publisher.publish_many.assert_not_called()
    finally:
        connection.close()


def test_direct_publication_remains_default() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE orders (id TEXT PRIMARY KEY)")
    event = DomainEvent(aggregate_id=OrderId.generate(), aggregate_type="Order")
    publisher = Mock()
    try:
        execute_use_case(
            handler=Handler(connection, event),
            input="1",
            unit_of_work=SqliteUow(connection),
            event_dispatcher=Mock(),
            event_publisher=publisher,
        )
        publisher.publish_many.assert_called_once_with([event])
    finally:
        connection.close()


def test_outbox_survives_dispatch_failure_after_commit(tmp_path: Path) -> None:
    db = str(tmp_path / "outbox.sqlite")
    with sqlite3.connect(db) as setup:
        setup.execute("CREATE TABLE orders (id TEXT PRIMARY KEY)")
        setup.execute("CREATE TABLE outbox (event_id TEXT PRIMARY KEY)")
    connection = sqlite3.connect(db)
    event = DomainEvent(aggregate_id=OrderId.generate(), aggregate_type="Order")
    dispatcher, publisher = Mock(), Mock()
    dispatcher.dispatch_many.side_effect = RuntimeError("dispatch failed")
    try:
        with pytest.raises(RuntimeError, match="dispatch failed"):
            execute_use_case(
                handler=Handler(connection, event),
                input="order-1",
                unit_of_work=SqliteUow(connection),
                event_dispatcher=dispatcher,
                event_publisher=publisher,
                outbox_writer=Outbox(connection),
            )
        with sqlite3.connect(db) as reader:
            assert reader.execute("SELECT id FROM orders").fetchall() == [("order-1",)]
            assert reader.execute("SELECT event_id FROM outbox").fetchall() == [
                (str(event.event_id),)
            ]
        publisher.publish_many.assert_not_called()
    finally:
        connection.close()
