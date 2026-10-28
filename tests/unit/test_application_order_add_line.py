"""Pruebas con fakes, sin garantías de base de datos real."""

from dataclasses import replace
from decimal import Decimal
from threading import Lock
from uuid import uuid4

import pytest

from tests.unit.test_application_catalog import FakeEventPublisher
from tests.unit.test_application_order_create import run, scoped
from tests.unit.test_application_reservation_confirm import LockedStore
from tests.unit.test_application_reservation_create import FixedRepo
from universal_business.application.errors import ApplicationError, IdempotencyConflictError
from universal_business.application.idempotency import IdempotencyKey
from universal_business.application.orders.add_line import AddOrderLineHandler
from universal_business.application.orders.commands import AddOrderLine
from universal_business.application.unit_of_work import CommitNotAppliedError
from universal_business.domain.catalog.entities import Offering
from universal_business.domain.catalog.value_objects import CatalogItemStatus
from universal_business.domain.orders.entities import Order
from universal_business.domain.orders.events import OrderLineAdded
from universal_business.domain.orders.value_objects import OrderChannel, OrderStatus
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    OfferingId,
    OrderId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money


class Ledger:
    def __init__(self, order):
        self.order, self.lock = order, Lock()


class Transaction:
    def __init__(self, ledger):
        self.ledger, self.pending, self.held, self.failure = ledger, None, False, None

    def __enter__(self):
        return self

    def protect(self, **scope):
        self.ledger.lock.acquire()
        self.held = True

    def get(self, *, tenant_id, order_id):
        assert self.held
        return self.ledger.order

    def save(self, order):
        assert self.held
        self.pending = order

    def commit(self):
        if self.failure:
            raise self.failure
        if self.pending is not None:
            self.ledger.order = self.pending

    def __exit__(self, exc_type, exc, tb):
        self.pending = None
        if self.held:
            self.held = False
            self.ledger.lock.release()


class Policy:
    def __init__(self):
        self.result = True

    def approve(self, **kwargs):
        return self.result


@pytest.fixture
def case():
    tid, bid, lid, oid, fid = (
        TenantId.generate(),
        BusinessId.generate(),
        LocationId.generate(),
        OrderId.generate(),
        OfferingId.generate(),
    )
    order = Order(
        id=oid,
        tenant_id=tid,
        business_id=bid,
        location_id=lid,
        status=OrderStatus.DRAFT,
        channel=OrderChannel.WEB,
    )
    offering = Offering(
        id=fid,
        tenant_id=tid,
        business_id=bid,
        name="Servicio",
        status=CatalogItemStatus.ACTIVE,
        base_price=Money(10, "EUR"),
    )
    cmd = AddOrderLine(
        tenant_id=tid,
        business_id=bid,
        location_id=lid,
        order_id=oid,
        offering_id=fid,
        line_id=uuid4(),
        quantity=Decimal(2),
        discount=Money(1, "EUR"),
        tax=Money(2, "EUR"),
        idempotency_key=IdempotencyKey(value="add-line-001"),
    )
    ledger, store, offers, policy = Ledger(order), LockedStore(), FixedRepo(offering), Policy()
    tx = Transaction(ledger)
    handler = AddOrderLineHandler(
        orders=tx, offerings=offers, guard=tx, policy=policy, idempotency=store
    )
    return cmd, ledger, tx, store, offers, policy, handler


def test_add_line_and_idempotent_replay(case):
    cmd, ledger, tx, _, _, _, handler = case
    publisher = FakeEventPublisher()
    result = run(handler, tx, cmd, publisher)
    assert result.total == Money(21, "EUR")
    assert ledger.order.lines[0].name == "Servicio"
    assert ledger.order.total == result.total
    assert len(publisher.published) == 1 and isinstance(publisher.published[0], OrderLineAdded)
    assert run(handler, tx, cmd, publisher) == result
    assert len(ledger.order.lines) == 1 and len(publisher.published) == 1
    with pytest.raises(IdempotencyConflictError):
        run(handler, tx, replace(cmd, quantity=Decimal(3)), publisher)


@pytest.mark.parametrize("approved", [True, False])
def test_policy_mutation_does_not_modify_repository_entities(case, approved):
    cmd, ledger, tx, _, offers, policy, handler = case
    original_order, original_offer = ledger.order, offers.value

    def mutate(*, order, offering, line):
        order.notes = "changed by policy"
        order.business_id = BusinessId.generate()
        offering.name = "changed by policy"
        offering.base_price = Money(999, "EUR")
        return approved

    policy.approve = mutate
    publisher = FakeEventPublisher()
    if approved:
        result = run(handler, tx, cmd, publisher)
        assert result.total == Money(21, "EUR")
        assert ledger.order.business_id == cmd.business_id
        assert ledger.order.notes is None
        assert ledger.order.lines[0].name == "Servicio"
    else:
        with pytest.raises(ApplicationError):
            run(handler, tx, cmd, publisher)
        assert ledger.order is original_order and not publisher.published
    assert original_order.business_id == cmd.business_id and original_order.notes is None
    assert original_offer.name == "Servicio" and original_offer.base_price == Money(10, "EUR")


@pytest.mark.parametrize("approved", [True, False])
def test_nested_metadata_is_isolated(case, approved):
    cmd, ledger, tx, _, offers, policy, handler = case
    offers.value = replace(offers.value, metadata={"rules": {"tags": ["original"]}})
    original_offer, original_order = offers.value, ledger.order

    def mutate(*, order, offering, line):
        offering.metadata["rules"]["tags"].append("changed")
        return approved

    policy.approve = mutate
    publisher = FakeEventPublisher()
    if approved:
        run(handler, tx, cmd, publisher)
        assert len(ledger.order.lines) == 1
    else:
        with pytest.raises(ApplicationError):
            run(handler, tx, cmd, publisher)
        assert ledger.order is original_order and not publisher.published
    assert original_offer.metadata["rules"]["tags"] == ["original"]


def test_noncopyable_metadata_fails_and_releases_key(case):
    cmd, ledger, tx, store, offers, _, handler = case
    offers.value = replace(offers.value, metadata={"lock": Lock()})
    publisher = FakeEventPublisher()
    with pytest.raises(ApplicationError, match="metadatos"):
        run(handler, tx, cmd, publisher)
    assert not ledger.order.lines and not publisher.published
    assert store.reserve(cmd.tenant_id, scoped(cmd), "retry")


@pytest.mark.parametrize("invalid", ["scope", "offering", "policy", "state", "duplicate"])
def test_rejection_has_no_committed_change(case, invalid):
    cmd, ledger, tx, store, offers, policy, handler = case
    if invalid == "scope":
        ledger.order = replace(ledger.order, business_id=BusinessId.generate())
    if invalid == "offering":
        offers.value = replace(offers.value, id=OfferingId.generate())
    if invalid == "policy":
        policy.result = False
    if invalid == "state":
        ledger.order = replace(ledger.order, status=OrderStatus.CONFIRMED)
    if invalid == "duplicate":
        original = run(handler, tx, cmd, FakeEventPublisher())
        assert original.total == Money(21, "EUR")
        cmd = replace(cmd, idempotency_key=IdempotencyKey(value="different-key"))
    old = ledger.order
    publisher = FakeEventPublisher()
    with pytest.raises((ApplicationError, InvariantViolationError)):
        run(handler, tx, cmd, publisher)
    assert ledger.order is old and not publisher.published
    assert store.reserve(cmd.tenant_id, scoped(cmd), "retry")


@pytest.mark.parametrize(
    "error,released",
    [(CommitNotAppliedError("not applied"), True), (RuntimeError("unknown"), False)],
)
def test_failed_commit_retains_original(case, error, released):
    cmd, ledger, tx, store, _, _, handler = case
    original = ledger.order
    tx.failure = error
    publisher = FakeEventPublisher()
    with pytest.raises(type(error)):
        run(handler, tx, cmd, publisher)
    assert ledger.order is original and not publisher.published
    assert store.reserve(cmd.tenant_id, scoped(cmd), "retry") is released


def test_complete_failure_keeps_key_after_commit(case):
    cmd, ledger, tx, store, _, _, handler = case
    publisher = FakeEventPublisher()

    def fail(*args):
        raise RuntimeError("complete failed")

    store.complete = fail
    with pytest.raises(RuntimeError, match="complete failed"):
        run(handler, tx, cmd, publisher)
    assert len(ledger.order.lines) == 1 and len(publisher.published) == 1
    assert not store.reserve(cmd.tenant_id, scoped(cmd), "retry")


def test_concurrent_different_lines_are_serialized_by_fake_guard(case):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    cmd, ledger, first_tx, store, offers, policy, first_handler = case
    entered, attempted, resume = Event(), Event(), Event()
    original_save = first_tx.save

    def blocked_save(order):
        entered.set()
        if not resume.wait(5):
            raise TimeoutError("other execution did not start")
        original_save(order)

    first_tx.save = blocked_save
    second_tx = Transaction(ledger)
    original_protect = second_tx.protect

    def announce(**scope):
        attempted.set()
        original_protect(**scope)

    second_tx.protect = announce
    second = AddOrderLineHandler(
        orders=second_tx, offerings=offers, guard=second_tx, policy=policy, idempotency=store
    )
    second_cmd = replace(cmd, line_id=uuid4(), idempotency_key=IdempotencyKey(value="add-line-002"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(run, first_handler, first_tx, cmd, FakeEventPublisher())
        assert entered.wait(5)
        second_future = pool.submit(run, second, second_tx, second_cmd, FakeEventPublisher())
        try:
            assert attempted.wait(5)
        finally:
            resume.set()
        first_future.result(timeout=5)
        second_future.result(timeout=5)
    assert len(ledger.order.lines) == 2
    assert ledger.order.total == Money(42, "EUR")
