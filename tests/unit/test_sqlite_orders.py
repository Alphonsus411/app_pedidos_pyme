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


def test_order_guard_requires_active_uow_and_exact_scope(case):
    from universal_business.application.errors import ApplicationError
    from universal_business.infrastructure.sqlite_orders import SqliteOrderMutationGuard
    from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork

    _, connection, repo, order = case
    connection.execute("BEGIN IMMEDIATE")
    repo.save(order)
    connection.commit()
    uow = SqliteUnitOfWork(connection)
    guard = SqliteOrderMutationGuard(uow)
    scope = dict(
        tenant_id=order.tenant_id,
        business_id=order.business_id,
        location_id=order.location_id,
        order_id=order.id,
    )
    with pytest.raises(RuntimeError, match="activa"):
        guard.protect(**scope)
    with uow:
        guard.protect(**scope)
        for changed in (
            dict(tenant_id=TenantId.generate()),
            dict(business_id=BusinessId.generate()),
            dict(location_id=LocationId.generate()),
            dict(order_id=OrderId.generate()),
        ):
            with pytest.raises(ApplicationError, match="no encontrado o fuera del ámbito"):
                guard.protect(**(scope | changed))
    with pytest.raises(RuntimeError, match="activa"):
        guard.protect(**scope)


def test_order_guard_serializes_writers_until_rollback(case):
    from universal_business.infrastructure.sqlite_orders import SqliteOrderMutationGuard
    from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork

    path, connection, repo, order = case
    connection.execute("BEGIN IMMEDIATE")
    repo.save(order)
    connection.commit()
    scope = dict(
        tenant_id=order.tenant_id,
        business_id=order.business_id,
        location_id=order.location_id,
        order_id=order.id,
    )
    with sqlite3.connect(path, timeout=0) as second:
        uow = SqliteUnitOfWork(connection)
        with uow:
            SqliteOrderMutationGuard(uow).protect(**scope)
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                with SqliteUnitOfWork(second):
                    pass
        with SqliteUnitOfWork(second) as next_uow:
            SqliteOrderMutationGuard(next_uow).protect(**scope)
            next_uow.commit()


def test_validate_and_confirm_order_using_real_sqlite_guard(case):
    from unittest.mock import Mock

    from tests.unit.test_application_reservation_confirm import LockedStore
    from universal_business.application.events.dispatcher import DomainEventDispatcher
    from universal_business.application.execution import execute_use_case
    from universal_business.application.idempotency import IdempotencyKey
    from universal_business.application.orders.commands import ConfirmOrder, ValidateOrder
    from universal_business.application.orders.status_change import (
        ConfirmOrderHandler,
        ValidateOrderHandler,
    )
    from universal_business.infrastructure.sqlite_orders import SqliteOrderMutationGuard
    from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork

    path, connection, repo, order = case
    connection.execute("BEGIN IMMEDIATE")
    repo.save(order)
    connection.commit()
    policy = Mock()
    policy.approve.return_value = True
    store = LockedStore()
    scope = dict(
        tenant_id=order.tenant_id,
        business_id=order.business_id,
        location_id=order.location_id,
        order_id=order.id,
    )
    for command, handler_type in (
        (
            ValidateOrder(**scope, idempotency_key=IdempotencyKey(value="order-validate-sqlite")),
            ValidateOrderHandler,
        ),
        (
            ConfirmOrder(**scope, idempotency_key=IdempotencyKey(value="order-confirm-sqlite")),
            ConfirmOrderHandler,
        ),
    ):
        uow = SqliteUnitOfWork(connection)
        handler = handler_type(
            orders=repo, guard=SqliteOrderMutationGuard(uow), policy=policy, idempotency=store
        )
        execute_use_case(
            handler=handler,
            input=command,
            unit_of_work=uow,
            event_dispatcher=DomainEventDispatcher(),
            event_publisher=Mock(),
        )
    with sqlite3.connect(path) as reader:
        saved = SqliteOrderRepository(reader).get(tenant_id=order.tenant_id, order_id=order.id)
        assert saved.status == OrderStatus.CONFIRMED
        assert saved.lines == order.lines


def test_concurrent_order_edits_keep_both_lines(case):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from universal_business.infrastructure.sqlite_orders import SqliteOrderMutationGuard
    from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork

    path, connection, repo, order = case
    connection.execute("BEGIN IMMEDIATE")
    repo.save(order)
    connection.commit()
    barrier = Barrier(2)
    new_ids = [uuid4(), uuid4()]
    scope = dict(
        tenant_id=order.tenant_id,
        business_id=order.business_id,
        location_id=order.location_id,
        order_id=order.id,
    )

    def edit(line_id):
        with sqlite3.connect(path, timeout=5) as conn:
            barrier.wait(timeout=5)
            with SqliteUnitOfWork(conn) as uow:
                SqliteOrderMutationGuard(uow).protect(**scope)
                store = SqliteOrderRepository(conn)
                current = store.get(tenant_id=order.tenant_id, order_id=order.id)
                current.add_line(replace(order.lines[0], line_id=line_id))
                store.save(current)
                uow.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(edit, new_ids))
    actual = repo.get(tenant_id=order.tenant_id, order_id=order.id)
    assert {line.line_id for line in actual.lines} == {order.lines[0].line_id, *new_ids}
