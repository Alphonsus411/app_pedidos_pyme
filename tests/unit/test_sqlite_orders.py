"""Persistencia de pedidos con SQLite real y aislamiento por tenant."""

import json
import sqlite3
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest

from universal_business.domain.orders.entities import Order
from universal_business.domain.orders.line import OrderLine
from universal_business.domain.orders.value_objects import OrderChannel, OrderStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CustomerId,
    LocationId,
    OfferingId,
    OrderId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money
from universal_business.infrastructure.sqlite_orders import (
    SqliteOrderRepository,
    create_sqlite_orders_schema,
)


@pytest.fixture
def case(tmp_path):
    path = tmp_path / "orders.db"
    connection = sqlite3.connect(path)
    create_sqlite_orders_schema(connection)
    order = Order(
        id=OrderId.generate(),
        tenant_id=TenantId.generate(),
        business_id=BusinessId.generate(),
        location_id=LocationId.generate(),
        customer_id=CustomerId.generate(),
        status=OrderStatus.DRAFT,
        channel=OrderChannel.WEB,
        notes="Nota",
        lines=(
            OrderLine(
                line_id=uuid4(),
                offering_id=OfferingId.generate(),
                name="Artículo",
                quantity=Decimal("1.2500"),
                unit_price=Money("19.9900", "EUR"),
                discount=Money("1.0000", "EUR"),
                tax=Money("2.5000", "EUR"),
            ),
        ),
    )
    yield path, connection, SqliteOrderRepository(connection), order
    connection.close()


def test_roundtrip_and_reopen_preserves_order_and_decimal(case):
    path, connection, repo, order = case
    connection.execute("BEGIN IMMEDIATE")
    repo.save(order)
    connection.commit()
    with sqlite3.connect(path) as reader:
        actual = SqliteOrderRepository(reader).get(tenant_id=order.tenant_id, order_id=order.id)
        assert actual == order
        assert actual.lines[0].quantity == Decimal("1.2500")
        assert actual.total == Money("26.4875", "EUR")
        assert actual.domain_events == []


def test_scope_filters_and_limits(case):
    _, connection, repo, order = case
    foreign = replace(order, id=OrderId.generate(), tenant_id=TenantId.generate())
    other = replace(
        order,
        id=OrderId.generate(),
        location_id=LocationId.generate(),
        customer_id=CustomerId.generate(),
    )
    connection.execute("BEGIN IMMEDIATE")
    for item in (order, foreign, other):
        repo.save(item)
    connection.commit()
    assert repo.get(tenant_id=foreign.tenant_id, order_id=order.id) is None
    assert [
        x.id
        for x in repo.list_by_location(tenant_id=order.tenant_id, location_id=order.location_id)
    ] == [order.id]
    assert [
        x.id
        for x in repo.list_by_customer(tenant_id=order.tenant_id, customer_id=order.customer_id)
    ] == [order.id]
    assert (
        repo.list_by_location(
            tenant_id=order.tenant_id, location_id=order.location_id, status=OrderStatus.CONFIRMED
        )
        == []
    )
    with pytest.raises(ValueError):
        repo.list_by_location(tenant_id=order.tenant_id, location_id=order.location_id, limit=0)


def test_rollback_and_immutable_scope(case):
    _, connection, repo, order = case
    with pytest.raises(RuntimeError, match="transacción"):
        repo.save(order)
    connection.execute("BEGIN IMMEDIATE")
    repo.save(order)
    connection.rollback()
    assert repo.get(tenant_id=order.tenant_id, order_id=order.id) is None
    connection.execute("BEGIN IMMEDIATE")
    repo.save(order)
    connection.commit()
    connection.execute("BEGIN IMMEDIATE")
    with pytest.raises(ValueError, match="ámbito"):
        repo.save(replace(order, business_id=BusinessId.generate()))
    connection.rollback()
    assert repo.get(tenant_id=order.tenant_id, order_id=order.id) == order


def test_corrupt_payload_fails_closed(case):
    _, connection, repo, order = case
    connection.execute("BEGIN IMMEDIATE")
    repo.save(order)
    payload = json.loads(connection.execute("SELECT payload FROM orders").fetchone()[0])
    payload["total"] = None
    connection.execute("UPDATE orders SET payload=?", (json.dumps(payload),))
    connection.commit()
    with pytest.raises(ValueError, match="Total"):
        repo.get(tenant_id=order.tenant_id, order_id=order.id)


def test_create_order_handler_uses_sqlite_repository(case):
    from tests.unit.test_application_reservation_confirm import LockedStore
    from tests.unit.test_application_reservation_create import FixedRepo
    from universal_business.application.idempotency import IdempotencyKey
    from universal_business.application.orders.commands import CreateOrder
    from universal_business.application.orders.creation import CreateOrderHandler
    from universal_business.domain.business.entities import Location
    from universal_business.domain.business.value_objects import (
        Address,
        LocationStatus,
        OperatingHours,
    )
    from universal_business.domain.customers.entities import Customer

    path, connection, repo, existing = case
    location = Location(
        id=existing.location_id,
        tenant_id=existing.tenant_id,
        business_id=existing.business_id,
        name="Local",
        address=Address(country_code="ES"),
        timezone="UTC",
        operating_hours=OperatingHours(),
        status=LocationStatus.OPEN,
    )
    customer = Customer(
        id=existing.customer_id,
        tenant_id=existing.tenant_id,
        business_id=existing.business_id,
        given_name="A",
    )
    command = CreateOrder(
        tenant_id=existing.tenant_id,
        business_id=existing.business_id,
        location_id=existing.location_id,
        order_id=OrderId.generate(),
        channel=OrderChannel.WEB,
        customer_id=existing.customer_id,
        idempotency_key=IdempotencyKey(value="sqlite-create-order"),
    )
    handler = CreateOrderHandler(
        orders=repo,
        locations=FixedRepo(location),
        customers=FixedRepo(customer),
        idempotency=LockedStore(),
    )
    connection.execute("BEGIN IMMEDIATE")
    result, events = handler.handle(command)
    connection.commit()
    with sqlite3.connect(path) as reader:
        saved = SqliteOrderRepository(reader).get(
            tenant_id=existing.tenant_id, order_id=command.order_id
        )
        assert saved is not None and saved.status == OrderStatus.DRAFT and saved.lines == ()
        assert result.order_id == command.order_id
        assert len(events) == 1
