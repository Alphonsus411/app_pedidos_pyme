"""Pruebas con fakes: no demuestran atomicidad de infraestructura."""

from dataclasses import replace

import pytest

from tests.unit.test_application_catalog import FakeEventPublisher
from tests.unit.test_application_reservation_confirm import LockedStore
from tests.unit.test_application_reservation_create import FixedRepo
from universal_business.application.errors import ApplicationError, IdempotencyConflictError
from universal_business.application.events.dispatcher import DomainEventDispatcher
from universal_business.application.execution import execute_use_case
from universal_business.application.idempotency import IdempotencyKey, scoped_idempotency_key
from universal_business.application.orders.commands import CreateOrder
from universal_business.application.orders.creation import CreateOrderHandler
from universal_business.application.unit_of_work import CommitNotAppliedError
from universal_business.domain.business.entities import Location
from universal_business.domain.business.value_objects import Address, LocationStatus, OperatingHours
from universal_business.domain.customers.entities import Customer
from universal_business.domain.orders.events import OrderCreated
from universal_business.domain.orders.value_objects import OrderChannel, OrderStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CustomerId,
    LocationId,
    OrderId,
    TenantId,
)


class Transaction:
    def __init__(self):
        self.rows = {}
        self.pending = None
        self.failure = None
        self.saves = 0

    def __enter__(self):
        self.pending = None
        return self

    def get(self, *, tenant_id, order_id):
        return self.rows.get(order_id)

    def save(self, order):
        self.pending = order
        self.saves += 1

    def commit(self):
        if self.failure:
            raise self.failure
        if self.pending is not None:
            self.rows[self.pending.id] = self.pending

    def __exit__(self, exc_type, exc, tb):
        self.pending = None


@pytest.fixture
def case():
    tid, bid, lid, cid = (
        TenantId.generate(),
        BusinessId.generate(),
        LocationId.generate(),
        CustomerId.generate(),
    )
    cmd = CreateOrder(
        tenant_id=tid,
        business_id=bid,
        location_id=lid,
        order_id=OrderId.generate(),
        channel=OrderChannel.WEB,
        customer_id=cid,
        idempotency_key=IdempotencyKey(value="create-order-001"),
    )
    location = Location(
        id=lid,
        tenant_id=tid,
        business_id=bid,
        name="Local",
        address=Address(country_code="ES"),
        timezone="Europe/Madrid",
        operating_hours=OperatingHours(),
        status=LocationStatus.OPEN,
    )
    customer = Customer(id=cid, tenant_id=tid, business_id=bid, given_name="A")
    tx, store, locs, customers = (
        Transaction(),
        LockedStore(),
        FixedRepo(location),
        FixedRepo(customer),
    )
    handler = CreateOrderHandler(orders=tx, locations=locs, customers=customers, idempotency=store)
    return cmd, tx, store, locs, customers, handler


def run(handler, tx, command, publisher):
    return execute_use_case(
        handler=handler,
        input=command,
        unit_of_work=tx,
        event_dispatcher=DomainEventDispatcher(),
        event_publisher=publisher,
    )


def scoped(command):
    return scoped_idempotency_key(
        business_id=command.business_id,
        operation=f"{type(command).__module__}.{type(command).__qualname__}",
        key=command.idempotency_key,
    )


def test_draft_replay_conflict_and_duplicate(case):
    cmd, tx, _, _, _, handler = case
    publisher = FakeEventPublisher()
    first = run(handler, tx, cmd, publisher)
    assert tx.rows[cmd.order_id].status == OrderStatus.DRAFT
    assert tx.rows[cmd.order_id].lines == ()
    assert len(publisher.published) == 1 and isinstance(publisher.published[0], OrderCreated)
    assert run(handler, tx, cmd, publisher) == first
    assert tx.saves == 1 and len(publisher.published) == 1
    with pytest.raises(IdempotencyConflictError):
        run(handler, tx, replace(cmd, channel=OrderChannel.PHONE), publisher)
    with pytest.raises(ApplicationError, match="ya existe"):
        run(
            handler,
            tx,
            replace(cmd, idempotency_key=IdempotencyKey(value="new-order-key")),
            publisher,
        )


def test_customer_is_optional(case):
    cmd, tx, _, _, customers, handler = case
    customers.value = None
    run(handler, tx, replace(cmd, customer_id=None), FakeEventPublisher())
    assert tx.rows[cmd.order_id].customer_id is None


@pytest.mark.parametrize("invalid", ["location", "closed", "customer", "channel"])
def test_invalid_input_releases_key(case, invalid):
    cmd, tx, store, locations, customers, handler = case
    if invalid == "location":
        locations.value = replace(locations.value, business_id=BusinessId.generate())
    if invalid == "closed":
        locations.value = replace(locations.value, status=LocationStatus.CLOSED)
    if invalid == "customer":
        customers.value = replace(customers.value, tenant_id=TenantId.generate())
    if invalid == "channel":
        cmd = replace(cmd, channel="web")
    publisher = FakeEventPublisher()
    with pytest.raises(ApplicationError):
        run(handler, tx, cmd, publisher)
    assert not tx.rows and not publisher.published
    assert store.reserve(cmd.tenant_id, scoped(cmd), "retry")


@pytest.mark.parametrize(
    "error,released",
    [(CommitNotAppliedError("not applied"), True), (RuntimeError("unknown"), False)],
)
def test_commit_failure(case, error, released):
    cmd, tx, store, _, _, handler = case
    tx.failure = error
    publisher = FakeEventPublisher()
    with pytest.raises(type(error)):
        run(handler, tx, cmd, publisher)
    assert not publisher.published
    assert store.reserve(cmd.tenant_id, scoped(cmd), "retry") is released


def test_complete_failure_keeps_key_after_commit(case):
    cmd, tx, store, _, _, handler = case
    publisher = FakeEventPublisher()

    def fail_complete(*args):
        raise RuntimeError("complete failed")

    store.complete = fail_complete
    with pytest.raises(RuntimeError, match="complete failed"):
        run(handler, tx, cmd, publisher)
    assert cmd.order_id in tx.rows
    assert len(publisher.published) == 1
    assert not store.reserve(cmd.tenant_id, scoped(cmd), "retry")


def test_cached_result_with_wrong_scope_is_rejected(case):
    from universal_business.application.orders.creation import OrderDraftCreated
    from universal_business.application.request_digest import request_digest

    cmd, tx, store, _, _, handler = case
    assert store.reserve(cmd.tenant_id, scoped(cmd), request_digest(cmd))
    store.complete(
        cmd.tenant_id,
        scoped(cmd),
        request_digest(cmd),
        OrderDraftCreated(
            tenant_id=cmd.tenant_id,
            business_id=BusinessId.generate(),
            location_id=cmd.location_id,
            order_id=cmd.order_id,
        ),
    )
    with pytest.raises(IdempotencyConflictError):
        run(handler, tx, cmd, FakeEventPublisher())
    assert not tx.rows


def test_failure_before_commit_releases_key_and_emits_no_event(case):
    cmd, tx, store, _, _, handler = case
    publisher = FakeEventPublisher()

    def fail_save(order):
        raise RuntimeError("storage failed")

    tx.save = fail_save
    with pytest.raises(RuntimeError, match="storage failed"):
        run(handler, tx, cmd, publisher)
    assert not tx.rows and not publisher.published
    assert store.reserve(cmd.tenant_id, scoped(cmd), "retry")


def test_concurrent_same_key_rejects_second_execution(case):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    cmd, first_tx, store, locations, customers, first_handler = case
    entered, resume = Event(), Event()
    original_save = first_tx.save

    def blocked_save(order):
        entered.set()
        if not resume.wait(5):
            raise TimeoutError("second execution did not complete")
        original_save(order)

    first_tx.save = blocked_save
    second_tx = Transaction()
    second_handler = CreateOrderHandler(
        orders=second_tx, locations=locations, customers=customers, idempotency=store
    )
    publisher = FakeEventPublisher()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run, first_handler, first_tx, cmd, publisher)
        try:
            assert entered.wait(5)
            with pytest.raises(IdempotencyConflictError):
                run(second_handler, second_tx, cmd, FakeEventPublisher())
        finally:
            resume.set()
        future.result(timeout=5)
    assert first_tx.saves == 1 and second_tx.saves == 0
    assert len(publisher.published) == 1
