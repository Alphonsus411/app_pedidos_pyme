"""Confirmación con dobles transaccionales; no acredita persistencia real."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier, Lock

import pytest

from tests.unit.test_application_catalog import FakeEventPublisher, FakeIdempotencyStore
from universal_business.application.errors import ApplicationError, IdempotencyConflictError
from universal_business.application.events.dispatcher import DomainEventDispatcher
from universal_business.application.execution import execute_use_case
from universal_business.application.idempotency import IdempotencyKey, scoped_idempotency_key
from universal_business.application.reservations.commands import ConfirmReservation
from universal_business.application.reservations.handlers import ConfirmReservationHandler
from universal_business.application.unit_of_work import CommitNotAppliedError
from universal_business.domain.customers.entities import Customer
from universal_business.domain.reservations.allocation import ReservationUnavailableError
from universal_business.domain.reservations.entities import Reservation
from universal_business.domain.reservations.events import ReservationConfirmed
from universal_business.domain.reservations.interval import ReservationInterval
from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.shared.errors import StatusTransitionError
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CustomerId,
    LocationId,
    ReservationId,
    ResourceId,
    TenantId,
)
from universal_business.domain.shared.value_objects.temporal import TimeRange


class LockedStore(FakeIdempotencyStore):
    def __init__(self):
        super().__init__()
        self.lock = Lock()

    def reserve(self, *args):
        with self.lock:
            return super().reserve(*args)

    def get(self, *args):
        with self.lock:
            return super().get(*args)

    def complete(self, *args):
        with self.lock:
            return super().complete(*args)

    def release(self, *args):
        with self.lock:
            return super().release(*args)


class Ledger:
    def __init__(self):
        self.lock, self.rows = Lock(), {}
        self.fail_commit = None
        self.change_on_lock = None


class Transaction:
    """Fake lock global: no modela reglas, recursos ni persistencia real."""

    def __init__(self, ledger):
        self.ledger, self.pending, self.held = ledger, None, False

    def __enter__(self):
        return self

    def get(self, *, tenant_id, reservation_id):
        return self.ledger.rows.get(reservation_id)

    def save(self, reservation):
        assert self.held
        self.pending = reservation

    def protect_and_check(
        self,
        *,
        tenant_id,
        business_id,
        location_id,
        resource_id,
        reservation_id,
        interval,
        party_size,
    ):
        self.ledger.lock.acquire()
        self.held = True
        if self.ledger.change_on_lock is not None:
            self.ledger.change_on_lock(self.ledger.rows[reservation_id])
        for row in self.ledger.rows.values():
            if (
                row.id != reservation_id
                and row.resource_id == resource_id
                and row.status == ReservationStatus.CONFIRMED
            ):
                if interval.overlaps(ReservationInterval(row.time_range.start, row.time_range.end)):
                    raise ReservationUnavailableError("occupied")

    def commit(self):
        if self.ledger.fail_commit is not None:
            raise self.ledger.fail_commit
        if self.pending is not None:
            self.ledger.rows[self.pending.id] = self.pending

    def rollback(self):
        self.pending = None

    def __exit__(self, exc_type, exc, tb):
        if exc is not None:
            self.rollback()
        if self.held:
            self.ledger.lock.release()
            self.held = False


class Customers:
    def __init__(self, value):
        self.value = value

    def get(self, **kwargs):
        return self.value


@pytest.fixture
def case():
    tid, bid, lid, rid, cid = (
        TenantId.generate(),
        BusinessId.generate(),
        LocationId.generate(),
        ResourceId.generate(),
        CustomerId.generate(),
    )
    start = datetime(2026, 10, 28, 10, tzinfo=UTC)
    row = Reservation(
        id=ReservationId.generate(),
        tenant_id=tid,
        business_id=bid,
        location_id=lid,
        resource_id=rid,
        customer_id=cid,
        time_range=TimeRange(start, start + timedelta(hours=1)),
        party_size=2,
    )
    customer = Customer(id=cid, tenant_id=tid, business_id=bid, given_name="A")
    command = ConfirmReservation(
        tenant_id=tid,
        business_id=bid,
        location_id=lid,
        reservation_id=row.id,
        idempotency_key=IdempotencyKey(value="confirm-key-001"),
    )
    ledger, store = Ledger(), LockedStore()
    ledger.rows[row.id] = row
    return ledger, store, customer, command


def run(ledger, store, customer, command, publisher=None):
    tx = Transaction(ledger)
    handler = ConfirmReservationHandler(
        reservations=tx, customers=Customers(customer), allocation=tx, idempotency=store
    )
    return execute_use_case(
        handler=handler,
        input=command,
        unit_of_work=tx,
        event_dispatcher=DomainEventDispatcher(),
        event_publisher=publisher or FakeEventPublisher(),
    )


def scoped(command):
    return scoped_idempotency_key(
        business_id=command.business_id,
        operation=f"{type(command).__module__}.{type(command).__qualname__}",
        key=command.idempotency_key,
    )


def test_confirm_and_replay_emit_one_event(case):
    ledger, store, customer, command = case
    publisher = FakeEventPublisher()
    result = run(ledger, store, customer, command, publisher)
    assert ledger.rows[command.reservation_id].status == ReservationStatus.CONFIRMED
    assert len(publisher.published) == 1 and isinstance(
        publisher.published[0], ReservationConfirmed
    )
    assert run(ledger, store, customer, command, publisher) == result
    assert len(publisher.published) == 1
    with pytest.raises(IdempotencyConflictError):
        run(ledger, store, customer, replace(command, reservation_id=ReservationId.generate()))


def test_scope_customer_and_state_rejected_without_side_effects(case):
    ledger, store, customer, command = case
    with pytest.raises(ApplicationError, match="ámbito"):
        run(ledger, store, customer, replace(command, location_id=LocationId.generate()))
    assert ledger.rows[command.reservation_id].status == ReservationStatus.DRAFT
    with pytest.raises(ApplicationError, match="Customer"):
        run(ledger, store, replace(customer, business_id=BusinessId.generate()), command)
    ledger.rows[command.reservation_id] = replace(
        ledger.rows[command.reservation_id], status=ReservationStatus.CANCELLED
    )
    with pytest.raises(StatusTransitionError):
        run(ledger, store, customer, command)
    assert store.reserve(command.tenant_id, scoped(command), "can-retry")


def test_changed_draft_after_lock_is_rejected(case):
    ledger, store, customer, command = case

    def modify(row):
        row.party_size = 1

    ledger.change_on_lock = modify
    with pytest.raises(ApplicationError, match="cambió"):
        run(ledger, store, customer, command)
    assert ledger.rows[command.reservation_id].status == ReservationStatus.DRAFT
    assert store.reserve(command.tenant_id, scoped(command), "can-retry")


@pytest.mark.parametrize(
    "error, released",
    [(CommitNotAppliedError("not applied"), True), (RuntimeError("unknown"), False)],
)
def test_commit_failure_reservation_key_semantics(case, error, released):
    ledger, store, customer, command = case
    ledger.fail_commit = error
    publisher = FakeEventPublisher()
    with pytest.raises(type(error)):
        run(ledger, store, customer, command, publisher)
    assert publisher.published == []
    assert store.reserve(command.tenant_id, scoped(command), "retry") is released


def test_two_simultaneous_reservations_one_resource_only_one_confirms(case):
    ledger, store, customer, command = case
    second = replace(ledger.rows[command.reservation_id], id=ReservationId.generate())
    ledger.rows[second.id] = second
    command2 = replace(
        command, reservation_id=second.id, idempotency_key=IdempotencyKey(value="confirm-key-002")
    )
    barrier = Barrier(2)

    def invoke(cmd):
        barrier.wait(timeout=5)
        try:
            return run(ledger, store, customer, cmd)
        except ReservationUnavailableError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(invoke, (command, command2)))
    assert sum(item is not None for item in results) == 1
    assert sum(row.status == ReservationStatus.CONFIRMED for row in ledger.rows.values()) == 1
