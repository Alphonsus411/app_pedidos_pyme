"""Resultados de pedidos durables en la tabla SQLite de idempotencia."""

import sqlite3
from uuid import uuid4

import pytest

from universal_business.application.idempotency import IdempotencyKey
from universal_business.application.orders.add_line import OrderLineResult
from universal_business.application.orders.creation import OrderDraftCreated
from universal_business.application.orders.remove_line import OrderLineRemoval
from universal_business.application.orders.status_change import OrderStatusResult
from universal_business.domain.orders.value_objects import OrderStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    OfferingId,
    OrderId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money
from universal_business.infrastructure.sqlite_idempotency import create_sqlite_idempotency_schema
from universal_business.infrastructure.sqlite_order_idempotency import SqliteOrderIdempotencyStore
from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork


@pytest.mark.parametrize("kind", ["draft", "add", "remove", "status"])
def test_results_roundtrip_atomic_and_replay_after_reopen(tmp_path, kind):
    path = tmp_path / "orders.db"
    fields = dict(
        tenant_id=TenantId.generate(),
        business_id=BusinessId.generate(),
        location_id=LocationId.generate(),
        order_id=OrderId.generate(),
    )
    results = {
        "draft": OrderDraftCreated(**fields),
        "add": OrderLineResult(
            **fields,
            line_id=uuid4(),
            offering_id=OfferingId.generate(),
            total=Money("24.5678", "EUR"),
        ),
        "remove": OrderLineRemoval(**fields, line_id=uuid4(), total=None),
        "status": OrderStatusResult(
            **fields, status=OrderStatus.CONFIRMED, total=Money("24.5678", "EUR")
        ),
    }
    key = IdempotencyKey(value="order-test-key")
    with sqlite3.connect(path) as connection:
        create_sqlite_idempotency_schema(connection)
        store = SqliteOrderIdempotencyStore(connection)
        with SqliteUnitOfWork(connection) as uow:
            assert store.reserve(fields["tenant_id"], key, "digest")
            store.complete_in_uow(uow, fields["tenant_id"], key, "digest", results[kind])
            uow.commit()
    with sqlite3.connect(path) as connection:
        store = SqliteOrderIdempotencyStore(connection)
        with SqliteUnitOfWork(connection):
            assert not store.reserve(fields["tenant_id"], key, "digest")
            assert store.get(fields["tenant_id"], key) == ("digest", results[kind])
            assert store.get(TenantId.generate(), key) is None


def test_rollback_and_foreign_owner_rejected(tmp_path):
    path = tmp_path / "orders.db"
    tenant, key = TenantId.generate(), IdempotencyKey(value="order-test-key")
    result = OrderDraftCreated(
        tenant_id=tenant,
        business_id=BusinessId.generate(),
        location_id=LocationId.generate(),
        order_id=OrderId.generate(),
    )
    with sqlite3.connect(path) as connection:
        create_sqlite_idempotency_schema(connection)
        owner = SqliteOrderIdempotencyStore(connection)
        other = SqliteOrderIdempotencyStore(connection)
        with SqliteUnitOfWork(connection) as uow:
            assert owner.reserve(tenant, key, "digest")
            with pytest.raises(RuntimeError, match="propia"):
                other.complete_in_uow(uow, tenant, key, "digest", result)
            owner.complete_in_uow(uow, tenant, key, "digest", result)
        assert connection.execute("SELECT count(*) FROM idempotency").fetchone() == (0,)


def test_invalid_payload_rejected(tmp_path):
    tenant, key = TenantId.generate(), IdempotencyKey(value="order-test-key")
    with sqlite3.connect(tmp_path / "orders.db") as connection:
        create_sqlite_idempotency_schema(connection)
        connection.execute(
            "INSERT INTO idempotency VALUES (?, ?, ?, ?, ?, ?)",
            (str(tenant), key.value, "digest", "token", "done", '{"version":true,"kind":"draft"}'),
        )
        with pytest.raises(ValueError, match="inválido"):
            SqliteOrderIdempotencyStore(connection).get(tenant, key)


def test_create_order_domain_result_and_outbox_commit_atomically(tmp_path):
    from universal_business.application.events.business_event_codec import BusinessEventJsonCodec
    from universal_business.application.idempotency import scoped_idempotency_key
    from universal_business.application.orders.commands import CreateOrder
    from universal_business.application.orders.creation import CreateOrderHandler
    from universal_business.application.request_digest import request_digest
    from universal_business.domain.business.entities import Location
    from universal_business.domain.business.value_objects import (
        Address,
        LocationStatus,
        OperatingHours,
    )
    from universal_business.domain.orders.value_objects import OrderChannel
    from universal_business.infrastructure.sqlite_orders import (
        SqliteOrderRepository,
        create_sqlite_orders_schema,
    )
    from universal_business.infrastructure.sqlite_outbox import (
        SqliteOutboxWriter,
        create_sqlite_outbox_schema,
    )

    path = tmp_path / "flow.db"
    tid, bid, lid, oid = (
        TenantId.generate(),
        BusinessId.generate(),
        LocationId.generate(),
        OrderId.generate(),
    )
    location = Location(
        id=lid,
        tenant_id=tid,
        business_id=bid,
        name="Local",
        address=Address(country_code="ES"),
        timezone="UTC",
        operating_hours=OperatingHours(),
        status=LocationStatus.OPEN,
    )

    class Fixed:
        def get(self, **kwargs):
            return location

    command = CreateOrder(
        tenant_id=tid,
        business_id=bid,
        location_id=lid,
        order_id=oid,
        channel=OrderChannel.WEB,
        idempotency_key=IdempotencyKey(value="create-order-flow"),
    )
    with sqlite3.connect(path) as connection:
        create_sqlite_orders_schema(connection)
        create_sqlite_idempotency_schema(connection)
        create_sqlite_outbox_schema(connection)
        store = SqliteOrderIdempotencyStore(connection)
        handler = CreateOrderHandler(
            orders=SqliteOrderRepository(connection),
            locations=Fixed(),
            customers=Fixed(),
            idempotency=store,
        )
        with SqliteUnitOfWork(connection) as uow:
            result, events = handler.handle(command)
            key = scoped_idempotency_key(
                business_id=bid,
                operation=f"{type(command).__module__}.{type(command).__qualname__}",
                key=command.idempotency_key,
            )
            store.complete_in_uow(uow, tid, key, request_digest(command), result)
            SqliteOutboxWriter(connection=connection, encoder=BusinessEventJsonCodec()).write_many(
                events
            )
            uow.commit()
    with sqlite3.connect(path) as connection:
        assert SqliteOrderRepository(connection).get(tenant_id=tid, order_id=oid) is not None
        assert connection.execute("SELECT state FROM idempotency").fetchone() == ("done",)
        assert connection.execute("SELECT count(*) FROM transactional_outbox").fetchone() == (1,)
        handler = CreateOrderHandler(
            orders=SqliteOrderRepository(connection),
            locations=Fixed(),
            customers=Fixed(),
            idempotency=SqliteOrderIdempotencyStore(connection),
        )
        with SqliteUnitOfWork(connection):
            replay, events = handler.handle(command)
            assert replay == result and events == []
