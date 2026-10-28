"""Ciclo de vida protegido con fakes, sin garantías de base de datos."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest

from tests.unit.test_application_catalog import FakeEventPublisher
from tests.unit.test_application_reservation_cancel import GuardedTransaction
from tests.unit.test_application_reservation_confirm import case as case
from tests.unit.test_application_reservation_confirm import run as confirm
from universal_business.application.errors import ApplicationError, IdempotencyConflictError
from universal_business.application.events.dispatcher import DomainEventDispatcher
from universal_business.application.execution import execute_use_case
from universal_business.application.idempotency import IdempotencyKey, scoped_idempotency_key
from universal_business.application.reservations.commands import (
    CheckInReservation,
    CompleteReservation,
    MarkReservationNoShow,
)
from universal_business.application.reservations.status_change import (
    CheckInReservationHandler,
    CompleteReservationHandler,
    MarkReservationNoShowHandler,
)
from universal_business.application.unit_of_work import CommitNotAppliedError
from universal_business.domain.reservations.events import ReservationStatusChanged
from universal_business.domain.reservations.lifecycle import reservation_occupies_interval
from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.shared.errors import StatusTransitionError
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    ReservationId,
    TenantId,
)

TRANSITIONS = [
    (
        CheckInReservation,
        CheckInReservationHandler,
        ReservationStatus.CONFIRMED,
        ReservationStatus.CHECKED_IN,
    ),
    (
        CompleteReservation,
        CompleteReservationHandler,
        ReservationStatus.CHECKED_IN,
        ReservationStatus.COMPLETED,
    ),
    (
        MarkReservationNoShow,
        MarkReservationNoShowHandler,
        ReservationStatus.CONFIRMED,
        ReservationStatus.NO_SHOW,
    ),
]


def command_for(cls, original):
    return cls(
        tenant_id=original.tenant_id,
        business_id=original.business_id,
        location_id=original.location_id,
        reservation_id=original.reservation_id,
        idempotency_key=IdempotencyKey(value="status-key-001"),
    )


def run(ledger, store, command, handler_cls, publisher=None):
    tx = GuardedTransaction(ledger)
    handler = handler_cls(reservations=tx, guard=tx, idempotency=store)
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


@pytest.mark.parametrize("cls,handler_cls,source,target", TRANSITIONS)
def test_status_transition_replay_and_event(case, cls, handler_cls, source, target):
    ledger, store, _, original = case
    ledger.rows[original.reservation_id] = replace(
        ledger.rows[original.reservation_id], status=source
    )
    cmd, publisher = command_for(cls, original), FakeEventPublisher()
    result = run(ledger, store, cmd, handler_cls, publisher)
    assert result.status == target and ledger.rows[cmd.reservation_id].status == target
    assert len(publisher.published) == 1
    event = publisher.published[0]
    assert isinstance(event, ReservationStatusChanged)
    assert event.previous_status == source and event.new_status == target
    assert run(ledger, store, cmd, handler_cls, publisher) == result
    assert len(publisher.published) == 1
    with pytest.raises(IdempotencyConflictError):
        run(ledger, store, replace(cmd, reservation_id=ReservationId.generate()), handler_cls)
    assert reservation_occupies_interval(target) == (target != ReservationStatus.NO_SHOW)


@pytest.mark.parametrize("cls,handler_cls,source,target", TRANSITIONS)
def test_invalid_transition_and_wrong_scope_do_not_mutate(case, cls, handler_cls, source, target):
    ledger, store, _, original = case
    cmd = command_for(cls, original)
    ledger.rows[cmd.reservation_id] = replace(
        ledger.rows[cmd.reservation_id], status=ReservationStatus.CANCELLED
    )
    with pytest.raises(StatusTransitionError):
        run(ledger, store, cmd, handler_cls)
    assert ledger.rows[cmd.reservation_id].status == ReservationStatus.CANCELLED
    assert store.reserve(cmd.tenant_id, scoped(cmd), "retry")
    for field, typ in (
        ("tenant_id", TenantId),
        ("business_id", BusinessId),
        ("location_id", LocationId),
    ):
        wrong = replace(
            cmd,
            **{field: typ.generate()},
            idempotency_key=IdempotencyKey(value=f"other-{field}-001"),
        )
        with pytest.raises(ApplicationError, match="ámbito"):
            run(ledger, store, wrong, handler_cls)


@pytest.mark.parametrize("cls,handler_cls,source,target", TRANSITIONS)
@pytest.mark.parametrize(
    "error,released",
    [(CommitNotAppliedError("not applied"), True), (RuntimeError("unknown"), False)],
)
def test_commit_failure_retains_or_releases_key(
    case, cls, handler_cls, source, target, error, released
):
    ledger, store, _, original = case
    ledger.rows[original.reservation_id] = replace(
        ledger.rows[original.reservation_id], status=source
    )
    cmd = command_for(cls, original)
    ledger.fail_commit = error
    publisher = FakeEventPublisher()
    with pytest.raises(type(error)):
        run(ledger, store, cmd, handler_cls, publisher)
    assert publisher.published == []
    assert store.reserve(cmd.tenant_id, scoped(cmd), "retry") is released


def test_no_show_and_check_in_race_never_both_succeed(case):
    ledger, store, customer, original = case
    confirm(ledger, store, customer, original)
    checkin, noshow = (
        command_for(CheckInReservation, original),
        command_for(MarkReservationNoShow, original),
    )
    barrier = Barrier(2)

    def invoke(cmd, handler_cls):
        barrier.wait(timeout=5)
        try:
            return run(ledger, store, cmd, handler_cls)
        except (StatusTransitionError, ApplicationError):
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(invoke, checkin, CheckInReservationHandler)
        b = pool.submit(invoke, noshow, MarkReservationNoShowHandler)
        results = [a.result(timeout=5), b.result(timeout=5)]
    assert sum(result is not None for result in results) == 1
    assert ledger.rows[original.reservation_id].status in (
        ReservationStatus.CHECKED_IN,
        ReservationStatus.NO_SHOW,
    )


@pytest.mark.parametrize("cls,handler_cls,source,target", TRANSITIONS)
def test_changed_reservation_after_guard_is_rejected(case, cls, handler_cls, source, target):
    ledger, store, _, original = case
    ledger.rows[original.reservation_id] = replace(
        ledger.rows[original.reservation_id], status=source
    )
    cmd = command_for(cls, original)

    def modify(row):
        row.party_size = 1

    ledger.change_on_lock = modify
    publisher = FakeEventPublisher()
    with pytest.raises(ApplicationError, match="cambió"):
        run(ledger, store, cmd, handler_cls, publisher)
    assert ledger.rows[cmd.reservation_id].status == source
    assert not publisher.published
    assert store.reserve(cmd.tenant_id, scoped(cmd), "retry")
