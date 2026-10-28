"""Cancelación protegida usando dobles; no acredita transacciones reales."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest

from tests.unit.test_application_catalog import FakeEventPublisher
from tests.unit.test_application_reservation_confirm import Transaction
from tests.unit.test_application_reservation_confirm import case as case
from tests.unit.test_application_reservation_confirm import run as confirm
from universal_business.application.errors import ApplicationError, IdempotencyConflictError
from universal_business.application.events.dispatcher import DomainEventDispatcher
from universal_business.application.execution import execute_use_case
from universal_business.application.idempotency import IdempotencyKey, scoped_idempotency_key
from universal_business.application.reservations.cancellation import CancelReservationHandler
from universal_business.application.reservations.commands import CancelReservation
from universal_business.application.unit_of_work import CommitNotAppliedError
from universal_business.domain.reservations.conflicts import conflicting_reservation_ids
from universal_business.domain.reservations.events import ReservationCancelled
from universal_business.domain.reservations.interval import ReservationInterval
from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.shared.errors import StatusTransitionError
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    ReservationId,
    TenantId,
)


class GuardedTransaction(Transaction):
    def protect(self, *, tenant_id, business_id, location_id, resource_id, reservation_id):
        self.ledger.lock.acquire()
        self.held = True
        if self.ledger.change_on_lock is not None:
            self.ledger.change_on_lock(self.ledger.rows[reservation_id])


def cancellation_command(confirm_cmd):
    return CancelReservation(
        tenant_id=confirm_cmd.tenant_id,
        business_id=confirm_cmd.business_id,
        location_id=confirm_cmd.location_id,
        reservation_id=confirm_cmd.reservation_id,
        idempotency_key=IdempotencyKey(value="cancel-key-001"),
    )


def run_cancel(ledger, store, command, publisher=None):
    tx = GuardedTransaction(ledger)
    handler = CancelReservationHandler(reservations=tx, guard=tx, idempotency=store)
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


def test_cancel_confirmed_is_idempotent_and_releases_occupancy(case):
    ledger, store, customer, confirm_cmd = case
    confirm(ledger, store, customer, confirm_cmd)
    cmd = cancellation_command(confirm_cmd)
    publisher = FakeEventPublisher()
    first = run_cancel(ledger, store, cmd, publisher)
    assert ledger.rows[cmd.reservation_id].status == ReservationStatus.CANCELLED
    assert len(publisher.published) == 1 and isinstance(
        publisher.published[0], ReservationCancelled
    )
    assert run_cancel(ledger, store, cmd, publisher) == first
    assert len(publisher.published) == 1
    row = ledger.rows[cmd.reservation_id]
    assert not conflicting_reservation_ids(
        tenant_id=row.tenant_id,
        business_id=row.business_id,
        location_id=row.location_id,
        resource_id=row.resource_id,
        interval=ReservationInterval(row.time_range.start, row.time_range.end),
        reservations=[row],
    )
    with pytest.raises(IdempotencyConflictError):
        run_cancel(ledger, store, replace(cmd, reservation_id=ReservationId.generate()))


def test_cancel_draft_and_reject_terminal_or_checked_in(case):
    ledger, store, _, confirm_cmd = case
    cmd = cancellation_command(confirm_cmd)
    run_cancel(ledger, store, cmd)
    assert ledger.rows[cmd.reservation_id].status == ReservationStatus.CANCELLED
    for status in (
        ReservationStatus.CHECKED_IN,
        ReservationStatus.COMPLETED,
        ReservationStatus.CANCELLED,
        ReservationStatus.NO_SHOW,
    ):
        ledger.rows[cmd.reservation_id] = replace(ledger.rows[cmd.reservation_id], status=status)
        new = replace(cmd, idempotency_key=IdempotencyKey(value=f"key-{status.value}-001"))
        with pytest.raises(StatusTransitionError):
            run_cancel(ledger, store, new)
        assert ledger.rows[cmd.reservation_id].status == status


@pytest.mark.parametrize("field", ["tenant_id", "business_id", "location_id"])
def test_cross_scope_rejected_before_guard(case, field):
    ledger, store, _, confirm_cmd = case
    cmd = cancellation_command(confirm_cmd)
    wrong = {"tenant_id": TenantId, "business_id": BusinessId, "location_id": LocationId}[
        field
    ].generate()
    publisher = FakeEventPublisher()
    with pytest.raises(ApplicationError, match="ámbito"):
        run_cancel(ledger, store, replace(cmd, **{field: wrong}), publisher)
    assert ledger.rows[cmd.reservation_id].status == ReservationStatus.DRAFT
    assert not ledger.lock.locked() and publisher.published == []


def test_changed_draft_after_guard_is_rejected(case):
    ledger, store, _, confirm_cmd = case
    cmd = cancellation_command(confirm_cmd)

    def modify(row):
        row.party_size = 1

    ledger.change_on_lock = modify
    with pytest.raises(ApplicationError, match="cambió"):
        run_cancel(ledger, store, cmd)
    assert ledger.rows[cmd.reservation_id].status == ReservationStatus.DRAFT
    assert store.reserve(cmd.tenant_id, scoped(cmd), "retry")


@pytest.mark.parametrize(
    "error,released",
    [(CommitNotAppliedError("not applied"), True), (RuntimeError("unknown"), False)],
)
def test_commit_failure_preserves_expected_idempotency_state(case, error, released):
    ledger, store, _, confirm_cmd = case
    cmd = cancellation_command(confirm_cmd)
    ledger.fail_commit = error
    publisher = FakeEventPublisher()
    with pytest.raises(type(error)):
        run_cancel(ledger, store, cmd, publisher)
    assert not publisher.published
    assert store.reserve(cmd.tenant_id, scoped(cmd), "retry") is released


def test_confirmation_racing_cancellation_has_valid_serial_outcome(case):
    ledger, store, customer, confirm_cmd = case
    cancel_cmd = cancellation_command(confirm_cmd)
    barrier = Barrier(2)

    def do_confirm():
        barrier.wait(timeout=5)
        try:
            return ("confirm", confirm(ledger, store, customer, confirm_cmd))
        except (StatusTransitionError, ApplicationError):
            return ("confirm-rejected", None)

    def do_cancel():
        barrier.wait(timeout=5)
        try:
            return ("cancel", run_cancel(ledger, store, cancel_cmd))
        except (StatusTransitionError, ApplicationError):
            return ("cancel-rejected", None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(do_confirm), pool.submit(do_cancel)
        results = {a.result(timeout=5)[0], b.result(timeout=5)[0]}
    final_status = ledger.rows[cancel_cmd.reservation_id].status
    if "cancel" in results:
        assert final_status == ReservationStatus.CANCELLED
    else:
        assert results == {"confirm", "cancel-rejected"}
        assert final_status == ReservationStatus.CONFIRMED
