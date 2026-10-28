"""Evaluación pura de conflictos de reserva y aislamiento de ámbito."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from universal_business.domain.reservations.conflicts import conflicting_reservation_ids
from universal_business.domain.reservations.entities import Reservation
from universal_business.domain.reservations.interval import ReservationInterval
from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.shared.errors import InvariantViolationError, TemporalRangeError
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CustomerId,
    LocationId,
    ReservationId,
    ResourceId,
    TenantId,
)
from universal_business.domain.shared.value_objects.temporal import TimeRange


@pytest.fixture
def reservation():
    start = datetime(2026, 10, 28, 10, tzinfo=UTC)
    return Reservation(
        id=ReservationId.generate(),
        tenant_id=TenantId.generate(),
        business_id=BusinessId.generate(),
        location_id=LocationId.generate(),
        customer_id=CustomerId.generate(),
        resource_id=ResourceId.generate(),
        time_range=TimeRange(start, start + timedelta(hours=1)),
    )


def check(reservation, interval, records):
    return conflicting_reservation_ids(
        tenant_id=reservation.tenant_id,
        business_id=reservation.business_id,
        location_id=reservation.location_id,
        resource_id=reservation.resource_id,
        interval=interval,
        reservations=records,
    )


@pytest.mark.parametrize(
    ("status", "blocking"),
    [
        (ReservationStatus.DRAFT, False),
        (ReservationStatus.CONFIRMED, True),
        (ReservationStatus.CHECKED_IN, True),
        (ReservationStatus.COMPLETED, True),
        (ReservationStatus.CANCELLED, False),
        (ReservationStatus.NO_SHOW, False),
    ],
)
def test_status_controls_occupancy(reservation, status, blocking):
    record = replace(reservation, status=status)
    interval = ReservationInterval(record.time_range.start, record.time_range.end)
    assert check(record, interval, [record]) == ((record.id,) if blocking else ())


def test_overlap_is_half_open_and_deduplicated(reservation):
    record = replace(reservation, status=ReservationStatus.CONFIRMED)
    start, end = record.time_range.start, record.time_range.end
    assert check(record, ReservationInterval(end, end + timedelta(hours=1)), [record]) == ()
    assert check(
        record, ReservationInterval(start - timedelta(minutes=1), end), [record, record]
    ) == (record.id,)


@pytest.mark.parametrize("field", ["tenant_id", "business_id", "location_id", "resource_id"])
def test_foreign_scope_is_rejected_even_if_not_blocking(reservation, field):
    interval = ReservationInterval(reservation.time_range.start, reservation.time_range.end)
    foreign = replace(reservation, **{field: type(getattr(reservation, field)).generate()})
    with pytest.raises(InvariantViolationError, match="fuera del ámbito"):
        check(reservation, interval, [foreign])


def test_invalid_occupied_existing_interval_fails_closed(reservation):
    record = replace(
        reservation,
        status=ReservationStatus.CONFIRMED,
        time_range=TimeRange(reservation.time_range.start, reservation.time_range.start),
    )
    interval = ReservationInterval(reservation.time_range.start, reservation.time_range.end)
    with pytest.raises(TemporalRangeError):
        check(reservation, interval, [record])


def test_conflicts_sorted_by_id(reservation):
    first = replace(reservation, status=ReservationStatus.CONFIRMED)
    second = replace(first, id=ReservationId.generate())
    interval = ReservationInterval(first.time_range.start, first.time_range.end)
    assert check(first, interval, [second, first]) == tuple(sorted((first.id, second.id), key=str))
