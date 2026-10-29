"""Ensamblaje transaccional de operaciones de pedidos con SQLite real."""

import sqlite3
from decimal import Decimal
from unittest.mock import Mock
from uuid import uuid4

import pytest

from universal_business.application.errors import ApplicationError
from universal_business.application.idempotency import IdempotencyKey
from universal_business.application.orders.commands import (
    CancelOrder,
    CompleteOrder,
    ConfirmOrder,
    CreateOrder,
    DispatchOrder,
    MarkOrderReady,
    PrepareOrder,
    RemoveOrderLine,
    ReturnOrderToDraft,
    ValidateOrder,
)
from universal_business.domain.business.entities import Location
from universal_business.domain.business.value_objects import Address, LocationStatus, OperatingHours
from universal_business.domain.orders.line import OrderLine
from universal_business.domain.orders.value_objects import OrderChannel, OrderStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    OfferingId,
    OrderId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money
from universal_business.infrastructure.sqlite_locations import SqliteLocationRepository
from universal_business.infrastructure.sqlite_order_execution import SqliteOrderExecution
from universal_business.infrastructure.sqlite_orders import SqliteOrderRepository
from universal_business.infrastructure.sqlite_schema import initialize_sqlite_schema
from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork


@pytest.fixture
def context(tmp_path):
    connection = sqlite3.connect(tmp_path / "prototype.db")
    initialize_sqlite_schema(connection)
    tenant, business, location, order = (
        TenantId.generate(),
        BusinessId.generate(),
        LocationId.generate(),
        OrderId.generate(),
    )
    with SqliteUnitOfWork(connection) as uow:
        SqliteLocationRepository(connection).save(
            Location(
                id=location,
                tenant_id=tenant,
                business_id=business,
                name="Local",
                address=Address(country_code="ES"),
                timezone="UTC",
                operating_hours=OperatingHours(),
                status=LocationStatus.OPEN,
            )
        )
        uow.commit()
    policy = Mock()
    policy.approve.return_value = True
    service = SqliteOrderExecution(
        connection, dispatcher=Mock(), publisher=Mock(), transition_policy=policy
    )
    scope = dict(tenant_id=tenant, business_id=business, location_id=location, order_id=order)
    yield connection, service, scope, policy
    connection.close()


def _create(service, scope):
    command = CreateOrder(
        **scope, channel=OrderChannel.WEB, idempotency_key=IdempotencyKey(value="create-order-1")
    )
    assert service.create(command) == service.create(command)


def _line(connection, scope):
    line = OrderLine(
        line_id=uuid4(),
        offering_id=OfferingId.generate(),
        name="Producto",
        quantity=Decimal("1"),
        unit_price=Money("10", "EUR"),
        discount=Money("0", "EUR"),
        tax=Money("0", "EUR"),
    )
    with SqliteUnitOfWork(connection) as uow:
        repo = SqliteOrderRepository(connection)
        order = repo.get(tenant_id=scope["tenant_id"], order_id=scope["order_id"])
        order.add_line(line)
        repo.save(order)
        uow.commit()
    return line


def test_create_remove_and_all_main_statuses_with_atomic_replay(context):
    connection, service, scope, _ = context
    _create(service, scope)
    line = _line(connection, scope)
    remove = RemoveOrderLine(
        **scope, line_id=line.line_id, idempotency_key=IdempotencyKey(value="remove-line-1")
    )
    assert service.remove_line(remove) == service.remove_line(remove)
    _line(connection, scope)
    statuses = [
        (ValidateOrder, OrderStatus.VALIDATED),
        (ConfirmOrder, OrderStatus.CONFIRMED),
        (PrepareOrder, OrderStatus.PREPARING),
        (MarkOrderReady, OrderStatus.READY),
        (DispatchOrder, OrderStatus.DELIVERING),
        (CompleteOrder, OrderStatus.COMPLETED),
    ]
    for i, (cls, status) in enumerate(statuses):
        command = cls(**scope, idempotency_key=IdempotencyKey(value=f"status-key-{i}"))
        assert service.change_status(command).status == status
        assert service.change_status(command).status == status
    assert connection.execute("SELECT count(*) FROM transactional_outbox").fetchone() == (8,)
    assert connection.execute("SELECT count(*) FROM idempotency WHERE state='done'").fetchone() == (
        8,
    )
    assert (
        SqliteOrderRepository(connection)
        .get(tenant_id=scope["tenant_id"], order_id=scope["order_id"])
        .status
        == OrderStatus.COMPLETED
    )


def test_return_and_cancel_status(context):
    connection, service, scope, _ = context
    _create(service, scope)
    _line(connection, scope)
    for i, cls in enumerate((ValidateOrder, ReturnOrderToDraft, CancelOrder)):
        result = service.change_status(
            cls(**scope, idempotency_key=IdempotencyKey(value=f"status-key-{i}"))
        )
    assert result.status == OrderStatus.CANCELLED


def test_outbox_failure_rolls_back_order_and_idempotency(context):
    connection, service, scope, _ = context
    connection.execute(
        "CREATE TRIGGER reject_event BEFORE INSERT ON transactional_outbox BEGIN SELECT RAISE(ABORT, 'outbox failure'); END"
    )
    command = CreateOrder(
        **scope, channel=OrderChannel.WEB, idempotency_key=IdempotencyKey(value="create-fail-1")
    )
    with pytest.raises(sqlite3.IntegrityError, match="outbox failure"):
        service.create(command)
    assert connection.execute("SELECT count(*) FROM orders").fetchone() == (0,)
    assert connection.execute("SELECT count(*) FROM idempotency").fetchone() == (0,)
    assert connection.execute("SELECT count(*) FROM transactional_outbox").fetchone() == (0,)
    connection.execute("DROP TRIGGER reject_event")
    assert service.create(command).order_id == scope["order_id"]


def test_denied_transition_rolls_back(context):
    connection, service, scope, policy = context
    _create(service, scope)
    _line(connection, scope)
    policy.approve.return_value = False
    with pytest.raises(ApplicationError, match="Política"):
        service.change_status(
            ValidateOrder(**scope, idempotency_key=IdempotencyKey(value="denied-status"))
        )
    assert connection.execute("SELECT status FROM orders").fetchone() == ("draft",)
    assert connection.execute("SELECT count(*) FROM idempotency").fetchone() == (1,)
    assert connection.execute("SELECT count(*) FROM transactional_outbox").fetchone() == (1,)


def test_uncertain_commit_replay_without_duplicate(context):
    class CommitThenFail(sqlite3.Connection):
        def commit(self):
            super().commit()
            raise RuntimeError("uncertain commit")

    connection, service, scope, policy = context
    path = connection.execute("PRAGMA database_list").fetchone()[2]
    command = CreateOrder(
        **scope, channel=OrderChannel.WEB, idempotency_key=IdempotencyKey(value="uncertain-order")
    )
    with sqlite3.connect(path, factory=CommitThenFail) as failing:
        execution = SqliteOrderExecution(
            failing, dispatcher=Mock(), publisher=Mock(), transition_policy=policy
        )
        with pytest.raises(RuntimeError, match="uncertain commit"):
            execution.create(command)
    assert service.create(command).order_id == scope["order_id"]
    assert connection.execute("SELECT count(*) FROM transactional_outbox").fetchone() == (1,)
    assert connection.execute("SELECT state FROM idempotency").fetchone() == ("done",)


def test_real_offering_add_replay_and_complete_cycle(context):
    from universal_business.application.orders.commands import AddOrderLine
    from universal_business.domain.catalog.entities import Offering
    from universal_business.domain.catalog.value_objects import CatalogItemStatus
    from universal_business.infrastructure.sqlite_offerings import SqliteOfferingRepository

    connection, service, scope, _ = context
    _create(service, scope)
    offering = Offering(
        id=OfferingId.generate(),
        tenant_id=scope["tenant_id"],
        business_id=scope["business_id"],
        name="Producto",
        status=CatalogItemStatus.ACTIVE,
        base_price=Money("12.50", "EUR"),
        location_ids=frozenset({scope["location_id"]}),
    )
    with SqliteUnitOfWork(connection) as uow:
        SqliteOfferingRepository(connection).save(offering)
        uow.commit()
    command = AddOrderLine(
        **scope,
        offering_id=offering.id,
        line_id=uuid4(),
        quantity=Decimal("2"),
        discount=Money("1", "EUR"),
        tax=Money("2", "EUR"),
        idempotency_key=IdempotencyKey(value="add-line-real"),
    )
    policy = Mock()
    policy.approve.return_value = True
    first = service.add_line(command, policy=policy)
    assert first.total == Money("26", "EUR")
    assert service.add_line(command, policy=policy) == first
    assert policy.approve.call_count == 1
    for i, cls in enumerate(
        (ValidateOrder, ConfirmOrder, PrepareOrder, MarkOrderReady, CompleteOrder)
    ):
        service.change_status(
            cls(**scope, idempotency_key=IdempotencyKey(value=f"cycle-state-{i}"))
        )
    saved = SqliteOrderRepository(connection).get(
        tenant_id=scope["tenant_id"], order_id=scope["order_id"]
    )
    assert saved.status == OrderStatus.COMPLETED and saved.lines[0].offering_id == offering.id
    assert connection.execute("SELECT count(*) FROM transactional_outbox").fetchone() == (7,)
    assert connection.execute("SELECT count(*) FROM idempotency WHERE state='done'").fetchone() == (
        7,
    )


def test_add_line_rejects_inactive_and_policy_without_writes(context):
    from universal_business.application.orders.commands import AddOrderLine
    from universal_business.domain.catalog.entities import Offering
    from universal_business.domain.catalog.value_objects import CatalogItemStatus
    from universal_business.domain.shared.errors import InvariantViolationError
    from universal_business.infrastructure.sqlite_offerings import SqliteOfferingRepository

    connection, service, scope, _ = context
    _create(service, scope)
    offering = Offering(
        id=OfferingId.generate(),
        tenant_id=scope["tenant_id"],
        business_id=scope["business_id"],
        name="Oferta",
        status=CatalogItemStatus.INACTIVE,
        base_price=Money("10", "EUR"),
    )
    with SqliteUnitOfWork(connection) as uow:
        SqliteOfferingRepository(connection).save(offering)
        uow.commit()
    command = AddOrderLine(
        **scope,
        offering_id=offering.id,
        line_id=uuid4(),
        quantity=Decimal("1"),
        discount=Money("0", "EUR"),
        tax=Money("0", "EUR"),
        idempotency_key=IdempotencyKey(value="add-denied-01"),
    )
    policy = Mock()
    policy.approve.return_value = True
    with pytest.raises(InvariantViolationError):
        service.add_line(command, policy=policy)
    offering.activate()
    with SqliteUnitOfWork(connection) as uow:
        SqliteOfferingRepository(connection).save(offering)
        uow.commit()
    policy.approve.return_value = False
    with pytest.raises(ApplicationError):
        service.add_line(command, policy=policy)
    order = SqliteOrderRepository(connection).get(
        tenant_id=scope["tenant_id"], order_id=scope["order_id"]
    )
    assert order.lines == ()
    assert connection.execute("SELECT count(*) FROM transactional_outbox").fetchone() == (1,)
    assert connection.execute("SELECT count(*) FROM idempotency").fetchone() == (1,)


def test_add_line_outbox_failure_rolls_back(context):
    from universal_business.application.orders.commands import AddOrderLine
    from universal_business.domain.catalog.entities import Offering
    from universal_business.domain.catalog.value_objects import CatalogItemStatus
    from universal_business.infrastructure.sqlite_offerings import SqliteOfferingRepository

    connection, service, scope, _ = context
    _create(service, scope)
    offering = Offering(
        id=OfferingId.generate(),
        tenant_id=scope["tenant_id"],
        business_id=scope["business_id"],
        name="Oferta",
        status=CatalogItemStatus.ACTIVE,
        base_price=Money("10", "EUR"),
    )
    with SqliteUnitOfWork(connection) as uow:
        SqliteOfferingRepository(connection).save(offering)
        uow.commit()
    command = AddOrderLine(
        **scope,
        offering_id=offering.id,
        line_id=uuid4(),
        quantity=Decimal("1"),
        discount=Money("0", "EUR"),
        tax=Money("0", "EUR"),
        idempotency_key=IdempotencyKey(value="add-fail-001"),
    )
    policy = Mock()
    policy.approve.return_value = True
    connection.execute(
        "CREATE TRIGGER reject_line BEFORE INSERT ON transactional_outbox BEGIN SELECT RAISE(ABORT, 'outbox failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="outbox failure"):
        service.add_line(command, policy=policy)
    assert (
        SqliteOrderRepository(connection)
        .get(tenant_id=scope["tenant_id"], order_id=scope["order_id"])
        .lines
        == ()
    )
    assert connection.execute("SELECT count(*) FROM idempotency").fetchone() == (1,)
    connection.execute("DROP TRIGGER reject_line")
    assert service.add_line(command, policy=policy).line_id == command.line_id


def test_add_line_locks_catalog_until_commit(context):
    from universal_business.application.orders.commands import AddOrderLine
    from universal_business.domain.catalog.entities import Offering
    from universal_business.domain.catalog.value_objects import CatalogItemStatus
    from universal_business.infrastructure.sqlite_offerings import SqliteOfferingRepository

    connection, service, scope, _ = context
    _create(service, scope)
    offering = Offering(
        id=OfferingId.generate(),
        tenant_id=scope["tenant_id"],
        business_id=scope["business_id"],
        name="Oferta",
        status=CatalogItemStatus.ACTIVE,
        base_price=Money("10", "EUR"),
    )
    with SqliteUnitOfWork(connection) as uow:
        SqliteOfferingRepository(connection).save(offering)
        uow.commit()
    command = AddOrderLine(
        **scope,
        offering_id=offering.id,
        line_id=uuid4(),
        quantity=Decimal("1"),
        discount=Money("0", "EUR"),
        tax=Money("0", "EUR"),
        idempotency_key=IdempotencyKey(value="add-lock-001"),
    )
    path = connection.execute("PRAGMA database_list").fetchone()[2]

    def approve(**kwargs):
        with sqlite3.connect(path, timeout=0) as other:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                with SqliteUnitOfWork(other):
                    pass
        return True

    policy = Mock()
    policy.approve.side_effect = approve
    assert service.add_line(command, policy=policy).total == Money("10", "EUR")
    assert policy.approve.call_count == 1
