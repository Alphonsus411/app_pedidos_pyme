"""Reglas temporales semiabiertas sin cambiar TimeRange existente."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from universal_business.domain.reservations.interval import ReservationInterval
from universal_business.domain.shared.errors import TemporalRangeError, TimezoneAwareRequiredError
from universal_business.domain.shared.value_objects.temporal import TimeRange


def test_adjacent_intervals_do_not_overlap_but_inclusive_timerange_does():
    a = datetime(2026, 1, 1, 10, tzinfo=UTC)
    b, c = a + timedelta(hours=1), a + timedelta(hours=2)
    assert not ReservationInterval(a, b).overlaps(ReservationInterval(b, c))
    assert TimeRange(a, b).overlaps(TimeRange(b, c))
    assert ReservationInterval(a, b).contains(a)
    assert not ReservationInterval(a, b).contains(b)


def test_overlaps_are_symmetric_and_duration_is_positive():
    a = datetime(2026, 1, 1, 10, tzinfo=UTC)
    first = ReservationInterval(a, a + timedelta(hours=2))
    second = ReservationInterval(a + timedelta(minutes=30), a + timedelta(hours=3))
    assert first.overlaps(second) and second.overlaps(first)
    assert first.duration == timedelta(hours=2)
    with pytest.raises(TemporalRangeError):
        ReservationInterval(a, a)
    with pytest.raises(TemporalRangeError):
        ReservationInterval(a, a - timedelta(seconds=1))


def test_naive_datetimes_rejected():
    aware = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(TimezoneAwareRequiredError):
        ReservationInterval(datetime(2026, 1, 1), aware)
    with pytest.raises(TimezoneAwareRequiredError):
        ReservationInterval(aware, aware + timedelta(hours=1)).contains(datetime(2026, 1, 1))


def test_dst_folds_are_compared_as_instants_not_wall_clock():
    madrid = ZoneInfo("Europe/Madrid")
    first = datetime(2026, 10, 25, 2, 30, tzinfo=madrid, fold=0)
    second = datetime(2026, 10, 25, 2, 30, tzinfo=madrid, fold=1)
    interval = ReservationInterval(first, second)
    assert interval.duration == timedelta(hours=1)
    assert interval.start.tzinfo is UTC and interval.end.tzinfo is UTC
    with pytest.raises(TemporalRangeError):
        ReservationInterval(second, first)


def test_equivalent_timezones_compare_as_same_instant():
    start = datetime(2026, 1, 1, 10, tzinfo=UTC)
    interval = ReservationInterval(start, start + timedelta(hours=1))
    equivalent = start.astimezone(ZoneInfo("Europe/Madrid"))
    assert interval.contains(equivalent)
    assert interval == ReservationInterval(equivalent, interval.end)
