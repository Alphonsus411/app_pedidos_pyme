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


def test_from_local_rejects_spring_gap_and_accepts_valid_neighbors():
    madrid = ZoneInfo("Europe/Madrid")
    with pytest.raises(TemporalRangeError, match="no existe"):
        ReservationInterval.from_local(
            datetime(2026, 3, 29, 2, 30), datetime(2026, 3, 29, 4), madrid
        )
    interval = ReservationInterval.from_local(
        datetime(2026, 3, 29, 1, 30), datetime(2026, 3, 29, 3, 30), madrid
    )
    assert interval.duration == timedelta(hours=1)


def test_from_local_ambiguous_time_requires_explicit_fold():
    madrid = ZoneInfo("Europe/Madrid")
    local = datetime(2026, 10, 25, 2, 30)
    with pytest.raises(TemporalRangeError, match="ambigua"):
        ReservationInterval.from_local(local, datetime(2026, 10, 25, 4), madrid)
    interval = ReservationInterval.from_local(local, local, madrid, start_fold=0, end_fold=1)
    assert interval.duration == timedelta(hours=1)
    with pytest.raises(TemporalRangeError, match="anterior"):
        ReservationInterval.from_local(local, local, madrid, start_fold=1, end_fold=0)


def test_local_resolution_requires_naive_input_and_valid_fold():
    from universal_business.domain.reservations.local_time import resolve_local_datetime

    zone = ZoneInfo("Europe/Madrid")
    with pytest.raises(TemporalRangeError, match="sin zona"):
        resolve_local_datetime(datetime(2026, 1, 1, tzinfo=UTC), zone)
    with pytest.raises(ValueError, match="fold"):
        resolve_local_datetime(datetime(2026, 1, 1), zone, fold=2)
    with pytest.raises(ValueError, match="fold"):
        resolve_local_datetime(datetime(2026, 1, 1), zone, fold=True)
    with pytest.raises(TypeError, match="ZoneInfo"):
        resolve_local_datetime(datetime(2026, 1, 1), UTC)


def test_non_hour_transition_and_skipped_day():
    from universal_business.domain.reservations.local_time import resolve_local_datetime

    lord_howe = ZoneInfo("Australia/Lord_Howe")
    repeated = datetime(2026, 4, 5, 1, 45)
    with pytest.raises(TemporalRangeError, match="ambigua"):
        resolve_local_datetime(repeated, lord_howe)
    assert resolve_local_datetime(repeated, lord_howe, fold=1) - resolve_local_datetime(
        repeated, lord_howe, fold=0
    ) == timedelta(minutes=30)
    with pytest.raises(TemporalRangeError, match="no existe"):
        resolve_local_datetime(datetime(2011, 12, 30, 12), ZoneInfo("Pacific/Apia"))
