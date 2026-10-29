"""Política temporal de ejemplo con reloj fijo, no política por defecto."""

from dataclasses import replace
from datetime import timedelta

import pytest

from tests.unit.test_application_catalog import FakeEventPublisher
from tests.unit.test_application_reservation_cancel import GuardedTransaction
from tests.unit.test_application_reservation_confirm import case as case
from tests.unit.test_application_reservation_status import command_for, scoped
from universal_business.application.errors import ApplicationError
from universal_business.application.events.dispatcher import DomainEventDispatcher
from universal_business.application.execution import execute_use_case
from universal_business.application.reservations.commands import MarkReservationNoShow
from universal_business.application.reservations.status_change import MarkReservationNoShowHandler
from universal_business.domain.reservations.value_objects import ReservationStatus


def execute(ledger, store, command, policy, publisher):
    tx = GuardedTransaction(ledger)
    handler = MarkReservationNoShowHandler(
        reservations=tx, guard=tx, idempotency=store, no_show_policy=policy
    )
    return execute_use_case(
        handler=handler,
        input=command,
        unit_of_work=tx,
        event_dispatcher=DomainEventDispatcher(),
        event_publisher=publisher,
    )


class GracePolicy:
    def __init__(self, now):
        self.now = now

    def approve(self, *, reservation):
        return self.now >= reservation.time_range.start + timedelta(minutes=15)


def test_missing_policy_fails_before_reserving_or_mutating(case):
    ledger, store, _, original = case
    cmd = command_for(MarkReservationNoShow, original)
    ledger.rows[cmd.reservation_id] = replace(
        ledger.rows[cmd.reservation_id], status=ReservationStatus.CONFIRMED
    )
    publisher = FakeEventPublisher()
    with pytest.raises(ApplicationError, match="política temporal"):
        execute(ledger, store, cmd, None, publisher)
    assert ledger.rows[cmd.reservation_id].status == ReservationStatus.CONFIRMED
    assert not publisher.published and store.reserve(cmd.tenant_id, scoped(cmd), "retry")


def test_policy_rejects_before_and_allows_at_threshold(case):
    ledger, store, _, original = case
    cmd = command_for(MarkReservationNoShow, original)
    ledger.rows[cmd.reservation_id] = replace(
        ledger.rows[cmd.reservation_id], status=ReservationStatus.CONFIRMED
    )
    start = ledger.rows[cmd.reservation_id].time_range.start
    publisher = FakeEventPublisher()
    with pytest.raises(ApplicationError, match="no aprobada"):
        execute(ledger, store, cmd, GracePolicy(start + timedelta(minutes=14)), publisher)
    assert ledger.rows[cmd.reservation_id].status == ReservationStatus.CONFIRMED
    assert not publisher.published
    result = execute(ledger, store, cmd, GracePolicy(start + timedelta(minutes=15)), publisher)
    assert result.status == ReservationStatus.NO_SHOW and len(publisher.published) == 1
    assert execute(ledger, store, cmd, GracePolicy(start), publisher) == result
    assert len(publisher.published) == 1  # El replay no vuelve a evaluar tiempo.


def test_policy_receives_copy_and_cannot_change_persisted_scope(case):
    ledger, store, _, original = case
    cmd = command_for(MarkReservationNoShow, original)
    ledger.rows[cmd.reservation_id] = replace(
        ledger.rows[cmd.reservation_id], status=ReservationStatus.CONFIRMED
    )

    class MutatingPolicy:
        def approve(self, *, reservation):
            reservation.notes = "changed"
            return False

    before = ledger.rows[cmd.reservation_id]
    with pytest.raises(ApplicationError):
        execute(ledger, store, cmd, MutatingPolicy(), FakeEventPublisher())
    assert ledger.rows[cmd.reservation_id] is before and before.notes is None
