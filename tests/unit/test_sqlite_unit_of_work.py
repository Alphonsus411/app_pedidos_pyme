"""Pruebas transaccionales del UoW SQLite con conexiones independientes."""

import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest

from universal_business.application.events.order_codec import OrderEventJsonCodec
from universal_business.application.execution import execute_use_case
from universal_business.domain.orders.events import OrderCreated
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    OrderId,
    TenantId,
)
from universal_business.infrastructure.sqlite_outbox import (
    SqliteOutboxWriter,
    create_sqlite_outbox_schema,
)
from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "uow.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE orders (id TEXT PRIMARY KEY)")
        create_sqlite_outbox_schema(connection)
    return path


def count(path: Path, table: str) -> int:
    assert table in {"orders", "transactional_outbox"}
    with sqlite3.connect(path) as connection:
        return int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def test_explicit_commit_and_idempotence(db_path: Path) -> None:
    connection = sqlite3.connect(db_path)
    try:
        uow = SqliteUnitOfWork(connection)
        with uow:
            connection.execute("INSERT INTO orders VALUES ('a')")
            assert count(db_path, "orders") == 0
            uow.commit()
            uow.commit()
        assert count(db_path, "orders") == 1
        assert connection.execute("SELECT 1").fetchone() == (1,)
        with pytest.raises(RuntimeError, match="UoW nueva"):
            uow.__enter__()
    finally:
        connection.close()


@pytest.mark.parametrize("fail", [False, True])
def test_no_commit_rolls_back(db_path: Path, fail: bool) -> None:
    with sqlite3.connect(db_path) as connection:

        def run() -> None:
            with SqliteUnitOfWork(connection):
                connection.execute("INSERT INTO orders VALUES ('a')")
                if fail:
                    raise RuntimeError("handler failed")

        if fail:
            with pytest.raises(RuntimeError, match="handler failed"):
                run()
        else:
            run()
    assert count(db_path, "orders") == 0


def test_rejects_existing_transaction_without_touching_it(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute("INSERT INTO orders VALUES ('original')")
        with pytest.raises(RuntimeError, match="sin transacción"):
            with SqliteUnitOfWork(connection):
                pass
        assert connection.in_transaction
        connection.rollback()
    assert count(db_path, "orders") == 0


def test_commit_failure_does_not_claim_it_was_not_applied(db_path: Path) -> None:
    class FailingConnection(sqlite3.Connection):
        def commit(self) -> None:
            raise sqlite3.OperationalError("commit outcome unknown")

    connection = sqlite3.connect(db_path, factory=FailingConnection)
    try:
        with pytest.raises(sqlite3.OperationalError, match="commit outcome unknown"):
            with SqliteUnitOfWork(connection) as uow:
                connection.execute("INSERT INTO orders VALUES ('a')")
                uow.commit()
        assert not connection.in_transaction
        assert count(db_path, "orders") == 0
    finally:
        connection.close()


def test_use_case_and_real_outbox_commit_together(db_path: Path) -> None:
    connection = sqlite3.connect(db_path)
    event = OrderCreated(
        aggregate_id=OrderId.generate(),
        tenant_id=TenantId.generate(),
        business_id=BusinessId.generate(),
        location_id=LocationId.generate(),
    )

    class Handler:
        def handle(self, value: str) -> tuple[str, list[OrderCreated]]:
            connection.execute("INSERT INTO orders VALUES (?)", (value,))
            return value, [event]

    publisher = Mock()
    try:
        assert (
            execute_use_case(
                handler=Handler(),
                input="a",
                unit_of_work=SqliteUnitOfWork(connection),
                event_dispatcher=Mock(),
                event_publisher=publisher,
                outbox_writer=SqliteOutboxWriter(
                    connection=connection, encoder=OrderEventJsonCodec()
                ),
            )
            == "a"
        )
        assert count(db_path, "orders") == 1
        assert count(db_path, "transactional_outbox") == 1
        publisher.publish_many.assert_not_called()
    finally:
        connection.close()


def test_outbox_encoding_error_rolls_back_domain(db_path: Path) -> None:
    connection = sqlite3.connect(db_path)
    event = OrderCreated(
        aggregate_id=OrderId.generate(),
        tenant_id=TenantId.generate(),
        business_id=BusinessId.generate(),
        location_id=LocationId.generate(),
        metadata={"unsupported": 1.2},
    )

    class Handler:
        def handle(self, value: str) -> tuple[str, list[OrderCreated]]:
            connection.execute("INSERT INTO orders VALUES (?)", (value,))
            return value, [event]

    try:
        with pytest.raises(ValueError, match="metadata"):
            execute_use_case(
                handler=Handler(),
                input="a",
                unit_of_work=SqliteUnitOfWork(connection),
                event_dispatcher=Mock(),
                event_publisher=Mock(),
                outbox_writer=SqliteOutboxWriter(
                    connection=connection, encoder=OrderEventJsonCodec()
                ),
            )
        assert count(db_path, "orders") == 0
        assert count(db_path, "transactional_outbox") == 0
    finally:
        connection.close()
