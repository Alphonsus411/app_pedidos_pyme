"""Reglas de disponibilidad sobre intervalos concretos ya expandidos."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from universal_business.domain.availability.evaluation import (
    AvailabilityReason,
    AvailabilityScope,
    ScopedAvailabilityPeriod,
    evaluate_availability,
)
from universal_business.domain.reservations.entities import Reservation
from universal_business.domain.reservations.interval import ReservationInterval
from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.resources.entities import Resource
from universal_business.domain.resources.value_objects import ResourceStatus
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CustomerId,
    LocationId,
    ReservationId,
    ResourceId,
    ResourceTypeId,
    TenantId,
)
from universal_business.domain.shared.value_objects.temporal import TimeRange


@pytest.fixture
def case():
    scope = AvailabilityScope(
        TenantId.generate(), BusinessId.generate(), LocationId.generate(), ResourceId.generate()
    )
    resource = Resource(
        id=scope.resource_id,
        tenant_id=scope.tenant_id,
        business_id=scope.business_id,
        location_id=scope.location_id,
        resource_type_id=ResourceTypeId.generate(),
        name="Sala",
        capacity=3,
    )
    start = datetime(2026, 10, 28, 10, tzinfo=UTC)
    requested = ReservationInterval(start, start + timedelta(hours=2))
    window = ScopedAvailabilityPeriod(scope, requested)
    return scope, resource, requested, window


def evaluate(case, *, windows=None, blocks=(), reservations=(), party_size=None, resource=None):
    scope, default_resource, requested, window = case
    return evaluate_availability(
        scope=scope,
        resource=resource or default_resource,
        requested=requested,
        windows=[window] if windows is None else windows,
        blocks=blocks,
        reservations=reservations,
        party_size=party_size,
    )


def test_no_windows_is_closed_and_full_window_is_available(case):
    assert evaluate(case, windows=[]).reason == AvailabilityReason.OUTSIDE_WINDOWS
    assert evaluate(case).available


def test_adjacent_windows_cover_but_a_gap_rejects(case):
    scope, _, request, _ = case
    middle = request.start + timedelta(hours=1)
    left = ScopedAvailabilityPeriod(scope, ReservationInterval(request.start, middle))
    right = ScopedAvailabilityPeriod(scope, ReservationInterval(middle, request.end))
    assert evaluate(case, windows=[right, left]).available
    gap = ScopedAvailabilityPeriod(
        scope, ReservationInterval(middle + timedelta(seconds=1), request.end)
    )
    assert evaluate(case, windows=[left, gap]).reason == AvailabilityReason.OUTSIDE_WINDOWS


def test_block_has_priority_and_adjacent_block_does_not_overlap(case):
    scope, _, request, _ = case
    block = ScopedAvailabilityPeriod(
        scope, ReservationInterval(request.start, request.start + timedelta(minutes=1))
    )
    assert evaluate(case, windows=[], blocks=[block]).reason == AvailabilityReason.BLOCKED
    adjacent = ScopedAvailabilityPeriod(
        scope, ReservationInterval(request.end, request.end + timedelta(hours=1))
    )
    assert evaluate(case, blocks=[adjacent]).available


def test_resource_state_and_capacity(case):
    _, resource, _, _ = case
    assert (
        evaluate(case, resource=replace(resource, status=ResourceStatus.INACTIVE)).reason
        == AvailabilityReason.INACTIVE_RESOURCE
    )
    assert evaluate(case, party_size=4).reason == AvailabilityReason.CAPACITY_EXCEEDED
    assert evaluate(case, party_size=3).available
    assert evaluate(case, resource=replace(resource, capacity=None), party_size=4).available
    for invalid in (0, -1, True, 1.5):
        with pytest.raises(InvariantViolationError):
            evaluate(case, party_size=invalid)


@pytest.mark.parametrize("field", ["tenant_id", "business_id", "location_id", "resource_id"])
def test_scoped_periods_reject_foreign_scope_even_when_resource_inactive(case, field):
    scope, resource, request, _ = case
    foreign = replace(scope, **{field: type(getattr(scope, field)).generate()})
    period = ScopedAvailabilityPeriod(foreign, request)
    with pytest.raises(InvariantViolationError, match="fuera del ámbito"):
        evaluate(case, windows=[period], resource=replace(resource, status=ResourceStatus.INACTIVE))
    with pytest.raises(InvariantViolationError, match="fuera del ámbito"):
        evaluate(case, blocks=[period])


def test_unassigned_resource_is_rejected(case):
    _, resource, _, _ = case
    with pytest.raises(InvariantViolationError, match="sin location"):
        evaluate(case, resource=replace(resource, location_id=None))


def test_conflicting_reservations_and_rejected_other_scope(case):
    scope, _, request, _ = case
    reservation = Reservation(
        id=ReservationId.generate(),
        tenant_id=scope.tenant_id,
        business_id=scope.business_id,
        location_id=scope.location_id,
        resource_id=scope.resource_id,
        customer_id=CustomerId.generate(),
        time_range=TimeRange(request.start, request.end),
        status=ReservationStatus.CONFIRMED,
    )
    result = evaluate(case, reservations=[reservation])
    assert result.reason == AvailabilityReason.RESERVATION_CONFLICT
    assert result.conflict_ids == (reservation.id,)
    assert evaluate(
        case, reservations=[replace(reservation, status=ReservationStatus.CANCELLED)]
    ).available
    with pytest.raises(InvariantViolationError, match="fuera del ámbito"):
        evaluate(case, reservations=[replace(reservation, tenant_id=TenantId.generate())])


def test_mutated_resource_fields_fail_closed(case):
    _, resource, _, _ = case
    object.__setattr__(resource, "status", "active")
    with pytest.raises(InvariantViolationError, match="Estado de recurso"):
        evaluate(case)
    object.__setattr__(resource, "status", ResourceStatus.ACTIVE)
    object.__setattr__(resource, "capacity", True)
    with pytest.raises(InvariantViolationError, match="Capacidad"):
        evaluate(case)
