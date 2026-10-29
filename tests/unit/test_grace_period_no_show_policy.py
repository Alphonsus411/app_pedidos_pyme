from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests.unit.test_application_catalog import FakeEventPublisher
from tests.unit.test_application_reservation_confirm import case as case
from tests.unit.test_application_reservation_status import command_for
from tests.unit.test_reservation_no_show_policy import execute
from universal_business.application.errors import ApplicationError
from universal_business.application.reservations.commands import MarkReservationNoShow
from universal_business.application.reservations.no_show_policy import GracePeriodNoShowPolicy
from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.shared.value_objects.temporal import TimeRange


def test_explicit_grace_boundary_and_utc_comparison(case):
    ledger, store, _, original = case
    cmd = command_for(MarkReservationNoShow, original)
    ledger.rows[cmd.reservation_id] = replace(
        ledger.rows[cmd.reservation_id], status=ReservationStatus.CONFIRMED
    )
    reservation = ledger.rows[cmd.reservation_id]
    deadline = reservation.time_range.start.astimezone(UTC) + timedelta(minutes=10)
    publisher = FakeEventPublisher()
    early = GracePeriodNoShowPolicy(
        clock=lambda: deadline - timedelta(microseconds=1), grace_period=timedelta(minutes=10)
    )
    with pytest.raises(ApplicationError, match="no aprobada"):
        execute(ledger, store, cmd, early, publisher)
    assert reservation.status == ReservationStatus.CONFIRMED and not publisher.published
    on_time = GracePeriodNoShowPolicy(clock=lambda: deadline, grace_period=timedelta(minutes=10))
    assert execute(ledger, store, cmd, on_time, publisher).status == ReservationStatus.NO_SHOW
    assert len(publisher.published) == 1


def test_dst_fold_uses_elapsed_time_not_wall_clock(case):
    ledger, _, _, original = case
    reservation = ledger.rows[original.reservation_id]
    start = datetime(2026, 10, 25, 2, 55, tzinfo=ZoneInfo("Europe/Madrid"), fold=0)
    reservation = replace(
        reservation, time_range=TimeRange(start, start.astimezone(UTC) + timedelta(hours=2))
    )
    after_fallback = datetime(2026, 10, 25, 2, 10, tzinfo=ZoneInfo("Europe/Madrid"), fold=1)
    policy = GracePeriodNoShowPolicy(
        clock=lambda: after_fallback, grace_period=timedelta(minutes=15)
    )
    assert policy.approve(reservation=reservation)


@pytest.mark.parametrize("invalid", [None, -1, timedelta(seconds=-1)])
def test_invalid_grace_is_rejected(invalid):
    with pytest.raises(ApplicationError):
        GracePeriodNoShowPolicy(clock=lambda: datetime.now(UTC), grace_period=invalid)


def test_naive_or_non_datetime_clock_is_rejected(case):
    ledger, _, _, original = case
    reservation = ledger.rows[original.reservation_id]
    for value in (datetime(2026, 1, 1), None):
        policy = GracePeriodNoShowPolicy(clock=lambda value=value: value, grace_period=timedelta(0))
        with pytest.raises(ApplicationError, match="reloj"):
            policy.approve(reservation=reservation)
