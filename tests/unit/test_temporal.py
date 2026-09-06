"""Tests unitarios para temporalidad: DateRange, TimeRange, require_aware."""

from __future__ import annotations

import datetime as dt

import pytest

from universal_business.domain.shared.errors import TemporalRangeError, TimezoneAwareRequiredError
from universal_business.domain.shared.value_objects.temporal import (
    UTC,
    DateRange,
    TimeRange,
    require_aware,
    to_utc,
)


def test_require_aware_rejects_naive() -> None:
    naive = dt.datetime(2025, 1, 1, 12, 0)
    with pytest.raises(TimezoneAwareRequiredError):
        require_aware(naive)


def test_require_aware_accepts_aware() -> None:
    aware = dt.datetime.now(UTC)
    assert require_aware(aware) is aware


def test_to_utc_converts_timezone() -> None:
    z5 = dt.timezone(dt.timedelta(hours=5))
    t = dt.datetime(2025, 1, 1, 12, 0, tzinfo=z5)  # 07:00 UTC
    u = to_utc(t)
    assert u.tzinfo is UTC
    assert u.hour == 7


def test_date_range_simple() -> None:
    dr = DateRange.from_iso("2025-01-01", "2025-01-10")
    assert dr.days == 10
    assert dt.date(2025, 1, 5) in dr
    assert dt.date(2025, 1, 11) not in dr
    # DateRange NO acepta datetime
    with pytest.raises(TemporalRangeError):
        DateRange(dt.datetime(2025, 1, 1), dt.datetime(2025, 1, 2))  # type: ignore[arg-type]


def test_date_range_start_after_end_raises() -> None:
    with pytest.raises(TemporalRangeError):
        DateRange.from_iso("2025-01-10", "2025-01-01")


def test_date_range_overlap_and_intersection() -> None:
    a = DateRange.from_iso("2025-01-01", "2025-01-10")
    b = DateRange.from_iso("2025-01-05", "2025-01-15")
    c = DateRange.from_iso("2025-02-01", "2025-02-05")
    assert a.overlaps(b)
    assert not a.overlaps(c)
    inter = a.intersection(b)
    assert inter is not None
    assert inter == DateRange.from_iso("2025-01-05", "2025-01-10")


def test_date_range_contains_subrange() -> None:
    outer = DateRange.from_iso("2025-01-01", "2025-01-31")
    inner = DateRange.from_iso("2025-01-10", "2025-01-15")
    assert inner in outer
    assert outer not in inner


def test_time_range_aware_required() -> None:
    naive = dt.datetime(2025, 1, 1, 10, 0)
    naive_end = dt.datetime(2025, 1, 1, 12, 0)
    with pytest.raises(TimezoneAwareRequiredError):
        TimeRange(naive, naive_end)  # type: ignore[arg-type]


def test_time_range_construct_and_duration() -> None:
    t1 = dt.datetime(2025, 1, 1, 10, 0, tzinfo=UTC)
    t2 = dt.datetime(2025, 1, 1, 12, 30, tzinfo=UTC)
    tr = TimeRange(t1, t2)
    assert tr.duration == dt.timedelta(hours=2, minutes=30)


def test_time_range_overlap() -> None:
    t1 = dt.datetime(2025, 1, 1, 10, 0, tzinfo=UTC)
    a = TimeRange(t1, t1 + dt.timedelta(hours=2))
    b = TimeRange(t1 + dt.timedelta(hours=1), t1 + dt.timedelta(hours=3))
    c = TimeRange(t1 + dt.timedelta(hours=4), t1 + dt.timedelta(hours=5))
    assert a.overlaps(b)
    assert not a.overlaps(c)
    inter = a.intersection(b)
    assert inter is not None
    assert inter.duration == dt.timedelta(hours=1)


def test_time_range_to_utc_properties() -> None:
    z5 = dt.timezone(dt.timedelta(hours=5))
    s = dt.datetime(2025, 1, 1, 12, 0, tzinfo=z5)
    e = s + dt.timedelta(hours=1)
    tr = TimeRange(s, e)
    assert tr.start_utc.hour == 7
    assert tr.end_utc.hour == 8
