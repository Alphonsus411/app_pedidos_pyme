from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from tests.unit.test_application_reservation_confirm import case as case
from universal_business.application.errors import ApplicationError
from universal_business.application.reservations.timing_policies import ReservationTimingPolicies


def test_boundaries_and_intentional_gap(case):
    ledger, _, _, cmd = case
    reservation = ledger.rows[cmd.reservation_id]
    start = reservation.time_range.start.astimezone(UTC)
    now = [start]
    policies = ReservationTimingPolicies(
        clock=lambda: now[0],
        early=timedelta(minutes=10),
        late=timedelta(minutes=5),
        grace_period=timedelta(minutes=8),
    )
    now[0] = start + timedelta(minutes=5)
    assert policies.check_in.approve(reservation=reservation)
    assert not policies.no_show.approve(reservation=reservation)
    now[0] = start + timedelta(minutes=6)
    assert not policies.check_in.approve(reservation=reservation)
    assert not policies.no_show.approve(reservation=reservation)
    now[0] = start + timedelta(minutes=8)
    assert not policies.check_in.approve(reservation=reservation)
    assert policies.no_show.approve(reservation=reservation)
    with pytest.raises(FrozenInstanceError):
        policies.late = timedelta(0)


@pytest.mark.parametrize(
    "late,grace",
    [
        (timedelta(minutes=5), timedelta(minutes=5)),
        (timedelta(minutes=6), timedelta(minutes=5)),
        (timedelta(0), timedelta(0)),
    ],
)
def test_overlap_is_rejected(late, grace):
    with pytest.raises(ApplicationError, match="debe superar"):
        ReservationTimingPolicies(
            clock=lambda: datetime.now(UTC), early=timedelta(0), late=late, grace_period=grace
        )


@pytest.mark.parametrize(
    "early,late,grace",
    [
        (timedelta(seconds=-1), timedelta(0), timedelta(1)),
        (timedelta(0), None, timedelta(1)),
        (timedelta(0), timedelta(0), timedelta(seconds=-1)),
    ],
)
def test_invalid_durations_are_rejected(early, late, grace):
    with pytest.raises(ApplicationError):
        ReservationTimingPolicies(
            clock=lambda: datetime.now(UTC), early=early, late=late, grace_period=grace
        )
