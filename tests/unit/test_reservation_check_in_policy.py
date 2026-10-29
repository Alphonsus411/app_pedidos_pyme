from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests.unit.test_application_catalog import FakeEventPublisher
from tests.unit.test_application_reservation_cancel import GuardedTransaction
from tests.unit.test_application_reservation_confirm import case as case
from tests.unit.test_application_reservation_status import command_for, scoped
from universal_business.application.errors import ApplicationError
from universal_business.application.events.dispatcher import DomainEventDispatcher
from universal_business.application.execution import execute_use_case
from universal_business.application.reservations.check_in_policy import CheckInWindowPolicy
from universal_business.application.reservations.commands import CheckInReservation
from universal_business.application.reservations.status_change import CheckInReservationHandler
from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.shared.value_objects.temporal import TimeRange


def execute(ledger, store, cmd, policy, publisher):
    tx = GuardedTransaction(ledger)
    handler = CheckInReservationHandler(
        reservations=tx, guard=tx, idempotency=store, check_in_policy=policy
    )
    return execute_use_case(
        handler=handler,
        input=cmd,
        unit_of_work=tx,
        event_dispatcher=DomainEventDispatcher(),
        event_publisher=publisher,
    )


def test_missing_policy_rejects_without_reserving(case):
    ledger, store, _, original = case
    cmd = command_for(CheckInReservation, original)
    ledger.rows[cmd.reservation_id] = replace(
        ledger.rows[cmd.reservation_id], status=ReservationStatus.CONFIRMED
    )
    publisher = FakeEventPublisher()
    with pytest.raises(ApplicationError, match="política temporal"):
        execute(ledger, store, cmd, None, publisher)
    assert ledger.rows[cmd.reservation_id].status == ReservationStatus.CONFIRMED
    assert not publisher.published and store.reserve(cmd.tenant_id, scoped(cmd), "retry")


def test_window_endpoints_and_replay(case):
    ledger, store, _, original = case
    cmd = command_for(CheckInReservation, original)
    ledger.rows[cmd.reservation_id] = replace(
        ledger.rows[cmd.reservation_id], status=ReservationStatus.CONFIRMED
    )
    reservation = ledger.rows[cmd.reservation_id]
    start = reservation.time_range.start.astimezone(UTC)
    early, late = timedelta(minutes=10), timedelta(minutes=20)
    for instant, accepted in (
        (start - early - timedelta(microseconds=1), False),
        (start - early, True),
        (start + late, True),
        (start + late + timedelta(microseconds=1), False),
    ):
        policy = CheckInWindowPolicy(clock=lambda instant=instant: instant, early=early, late=late)
        assert policy.approve(reservation=reservation) is accepted
    publisher = FakeEventPublisher()
    rejected = CheckInWindowPolicy(
        clock=lambda: start - early - timedelta(seconds=1), early=early, late=late
    )
    with pytest.raises(ApplicationError, match="no aprobada"):
        execute(ledger, store, cmd, rejected, publisher)
    accepted = CheckInWindowPolicy(clock=lambda: start, early=early, late=late)
    result = execute(ledger, store, cmd, accepted, publisher)
    assert result.status == ReservationStatus.CHECKED_IN and len(publisher.published) == 1
    assert execute(ledger, store, cmd, rejected, publisher) == result
    assert len(publisher.published) == 1


def test_fold_and_invalid_clock(case):
    ledger, _, _, original = case
    start = datetime(2026, 10, 25, 2, 55, tzinfo=ZoneInfo("Europe/Madrid"), fold=0)
    reservation = replace(
        ledger.rows[original.reservation_id],
        time_range=TimeRange(start, start.astimezone(UTC) + timedelta(hours=2)),
    )
    now = datetime(2026, 10, 25, 2, 10, tzinfo=ZoneInfo("Europe/Madrid"), fold=1)
    assert CheckInWindowPolicy(
        clock=lambda: now, early=timedelta(0), late=timedelta(minutes=15)
    ).approve(reservation=reservation)
    with pytest.raises(ApplicationError, match="reloj"):
        CheckInWindowPolicy(
            clock=lambda: datetime(2026, 1, 1), early=timedelta(0), late=timedelta(0)
        ).approve(reservation=reservation)


@pytest.mark.parametrize(
    "early,late", [(timedelta(seconds=-1), timedelta(0)), (timedelta(0), None)]
)
def test_invalid_configuration(early, late):
    with pytest.raises(ApplicationError):
        CheckInWindowPolicy(clock=lambda: datetime.now(UTC), early=early, late=late)
