"""Conversión explícita de reglas y bloqueos a periodos de disponibilidad."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from universal_business.domain.availability.entities import AvailabilityBlock, AvailabilityRule
from universal_business.domain.availability.evaluation import AvailabilityScope
from universal_business.domain.availability.materialization import materialize_availability_periods
from universal_business.domain.availability.value_objects import AvailabilityStatus, BlockReason
from universal_business.domain.business.entities import Location
from universal_business.domain.business.value_objects import Address, OperatingHours
from universal_business.domain.shared.errors import InvariantViolationError, TemporalRangeError
from universal_business.domain.shared.value_objects.ids import (
    AvailabilityBlockId,
    AvailabilityRuleId,
    BusinessId,
    LocationId,
    ResourceId,
    TenantId,
)
from universal_business.domain.shared.value_objects.temporal import DateRange, TimeRange


@pytest.fixture
def context():
    scope = AvailabilityScope(
        TenantId.generate(), BusinessId.generate(), LocationId.generate(), ResourceId.generate()
    )
    location = Location(
        id=scope.location_id,
        tenant_id=scope.tenant_id,
        business_id=scope.business_id,
        name="Local",
        address=Address(country_code="ES"),
        timezone="Europe/Madrid",
        operating_hours=OperatingHours(),
    )
    return scope, location


def rule(scope, *, dates=None, times=None, **kwargs):
    return AvailabilityRule(
        id=AvailabilityRuleId.generate(),
        tenant_id=scope.tenant_id,
        location_id=scope.location_id,
        effective_range=dates or DateRange.single(date(2026, 3, 29)),
        time_ranges=[] if times is None else times,
        **kwargs,
    )


def block(scope, *, dates=None, **kwargs):
    return AvailabilityBlock(
        id=AvailabilityBlockId.generate(),
        tenant_id=scope.tenant_id,
        location_id=scope.location_id,
        reason=BlockReason.HOLIDAY,
        blocked_range=dates or DateRange.single(date(2026, 3, 29)),
        **kwargs,
    )


def test_block_uses_local_day_length_across_dst(context):
    scope, location = context
    windows, blocks = materialize_availability_periods(
        scope=scope, location=location, rules=[], blocks=[block(scope)]
    )
    assert windows == ()
    assert blocks[0].interval.start == datetime(2026, 3, 28, 23, tzinfo=UTC)
    assert blocks[0].interval.duration == timedelta(hours=23)


def test_rule_absolute_times_are_clipped_to_inclusive_local_dates(context):
    scope, location = context
    raw = TimeRange(datetime(2026, 3, 28, 12, tzinfo=UTC), datetime(2026, 3, 30, 12, tzinfo=UTC))
    windows, blocks = materialize_availability_periods(
        scope=scope, location=location, rules=[rule(scope, times=[raw])], blocks=[]
    )
    assert blocks == ()
    assert windows[0].interval.start == datetime(2026, 3, 28, 23, tzinfo=UTC)
    assert windows[0].interval.end == datetime(2026, 3, 29, 22, tzinfo=UTC)
    assert raw.end == datetime(2026, 3, 30, 12, tzinfo=UTC)


def test_inactive_and_other_resource_do_not_apply(context):
    scope, location = context
    other = ResourceId.generate()
    output = materialize_availability_periods(
        scope=scope,
        location=location,
        rules=[rule(scope, status=AvailabilityStatus.INACTIVE), rule(scope, resource_id=other)],
        blocks=[block(scope, status=AvailabilityStatus.INACTIVE), block(scope, resource_id=other)],
    )
    assert output == ((), ())


@pytest.mark.parametrize("field", ["tenant_id", "location_id"])
def test_foreign_entities_fail_closed_even_if_inactive(context, field):
    scope, location = context
    obj = rule(scope, status=AvailabilityStatus.INACTIVE)
    foreign = replace(obj, **{field: type(getattr(obj, field)).generate()})
    with pytest.raises(InvariantViolationError, match="fuera del"):
        materialize_availability_periods(scope=scope, location=location, rules=[foreign], blocks=[])


def test_location_business_and_zone_validated(context):
    scope, location = context
    with pytest.raises(InvariantViolationError, match="Location fuera"):
        materialize_availability_periods(
            scope=scope,
            location=replace(location, business_id=BusinessId.generate()),
            rules=[],
            blocks=[],
        )
    with pytest.raises(InvariantViolationError, match="Zona horaria"):
        materialize_availability_periods(
            scope=scope, location=replace(location, timezone="Invalid/Zone"), rules=[], blocks=[]
        )


def test_capacity_and_zero_duration_fail_closed(context):
    scope, location = context
    with pytest.raises(InvariantViolationError, match="capacidad por regla"):
        materialize_availability_periods(
            scope=scope, location=location, rules=[rule(scope, capacity=2)], blocks=[]
        )
    t = datetime(2026, 3, 29, 9, tzinfo=UTC)
    with pytest.raises(TemporalRangeError):
        materialize_availability_periods(
            scope=scope, location=location, rules=[rule(scope, times=[TimeRange(t, t)])], blocks=[]
        )


def test_skipped_local_date_and_date_overflow_fail_closed(context):
    scope, location = context
    apia = replace(location, timezone="Pacific/Apia")
    with pytest.raises(TemporalRangeError, match="no existe"):
        materialize_availability_periods(
            scope=scope,
            location=apia,
            rules=[],
            blocks=[block(scope, dates=DateRange.single(date(2011, 12, 30)))],
        )
    with pytest.raises(TemporalRangeError, match="final del rango"):
        materialize_availability_periods(
            scope=scope,
            location=location,
            rules=[],
            blocks=[block(scope, dates=DateRange.single(date.max))],
        )


def test_materialized_periods_feed_evaluator(context):
    from universal_business.domain.availability.evaluation import (
        AvailabilityReason,
        evaluate_availability,
    )
    from universal_business.domain.reservations.interval import ReservationInterval
    from universal_business.domain.resources.entities import Resource
    from universal_business.domain.shared.value_objects.ids import ResourceTypeId

    scope, location = context
    start = datetime(2026, 3, 29, 9, tzinfo=UTC)
    requested = ReservationInterval(start, start + timedelta(hours=1))
    windows, blocks = materialize_availability_periods(
        scope=scope,
        location=location,
        rules=[rule(scope, times=[TimeRange(start, requested.end)])],
        blocks=[],
    )
    resource = Resource(
        id=scope.resource_id,
        tenant_id=scope.tenant_id,
        business_id=scope.business_id,
        resource_type_id=ResourceTypeId.generate(),
        location_id=scope.location_id,
        name="Sala",
    )
    assert evaluate_availability(
        scope=scope,
        resource=resource,
        requested=requested,
        windows=windows,
        blocks=blocks,
        reservations=[],
    ).available
    windows, blocks = materialize_availability_periods(
        scope=scope,
        location=location,
        rules=[rule(scope, times=[TimeRange(start, requested.end)])],
        blocks=[block(scope)],
    )
    assert (
        evaluate_availability(
            scope=scope,
            resource=resource,
            requested=requested,
            windows=windows,
            blocks=blocks,
            reservations=[],
        ).reason
        == AvailabilityReason.BLOCKED
    )


def test_malformed_resource_id_in_block_fails_closed(context):
    scope, location = context
    malformed = block(scope)
    malformed.resource_id = "malformed"
    with pytest.raises(InvariantViolationError, match="Recurso de bloqueo"):
        materialize_availability_periods(
            scope=scope, location=location, rules=[], blocks=[malformed]
        )
