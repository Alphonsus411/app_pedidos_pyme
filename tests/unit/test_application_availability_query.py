"""Consulta de disponibilidad con repositorios simulados y alcance explícito."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from universal_business.application.availability.handlers import EvaluateResourceAvailabilityHandler
from universal_business.application.availability.queries import EvaluateResourceAvailability
from universal_business.application.errors import ApplicationError
from universal_business.domain.availability.entities import AvailabilityBlock, AvailabilityRule
from universal_business.domain.availability.evaluation import AvailabilityReason
from universal_business.domain.availability.value_objects import BlockReason
from universal_business.domain.business.entities import Location
from universal_business.domain.business.value_objects import Address, LocationStatus, OperatingHours
from universal_business.domain.reservations.entities import Reservation
from universal_business.domain.reservations.interval import ReservationInterval
from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.resources.entities import Resource
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import (
    AvailabilityBlockId,
    AvailabilityRuleId,
    BusinessId,
    CustomerId,
    LocationId,
    ReservationId,
    ResourceId,
    ResourceTypeId,
    TenantId,
)
from universal_business.domain.shared.value_objects.temporal import DateRange, TimeRange


class LocationRepo:
    def __init__(self, value):
        self.value, self.calls = value, []

    def get(self, **kwargs):
        self.calls.append(kwargs)
        return self.value


class ResourceRepo:
    def __init__(self, value):
        self.value, self.calls = value, []

    def get(self, **kwargs):
        self.calls.append(kwargs)
        return self.value


class AvailabilityRepo:
    def __init__(self, rules, blocks):
        self.rules, self.blocks, self.calls = rules, blocks, []

    def list_rules_for_resource(self, **kwargs):
        self.calls.append(("rules", kwargs))
        return self.rules

    def list_blocks(self, **kwargs):
        self.calls.append(("blocks", kwargs))
        return self.blocks


class ReservationsRepo:
    def __init__(self, items):
        self.items, self.calls = items, []

    def list_for_resource_in_range(self, **kwargs):
        self.calls.append(kwargs)
        return self.items


@pytest.fixture
def case():
    tid, bid, lid, rid = (
        TenantId.generate(),
        BusinessId.generate(),
        LocationId.generate(),
        ResourceId.generate(),
    )
    location = Location(
        id=lid,
        tenant_id=tid,
        business_id=bid,
        name="Local",
        address=Address(country_code="ES"),
        timezone="Europe/Madrid",
        operating_hours=OperatingHours(),
        status=LocationStatus.OPEN,
    )
    resource = Resource(
        id=rid,
        tenant_id=tid,
        business_id=bid,
        location_id=lid,
        resource_type_id=ResourceTypeId.generate(),
        name="Sala",
        capacity=2,
    )
    start = datetime(2026, 3, 29, 9, tzinfo=UTC)
    end = start + timedelta(hours=1)
    q = EvaluateResourceAvailability(
        tenant_id=tid,
        business_id=bid,
        location_id=lid,
        resource_id=rid,
        interval=ReservationInterval(start, end),
        party_size=2,
    )
    rule = AvailabilityRule(
        id=AvailabilityRuleId.generate(),
        tenant_id=tid,
        location_id=lid,
        effective_range=DateRange.single(date(2026, 3, 29)),
        time_ranges=[TimeRange(start, end)],
    )
    loc_repo, resource_repo = LocationRepo(location), ResourceRepo(resource)
    avail_repo, reservations_repo = AvailabilityRepo([rule], []), ReservationsRepo([])
    handler = EvaluateResourceAvailabilityHandler(
        locations=loc_repo,
        resources=resource_repo,
        availability=avail_repo,
        reservations=reservations_repo,
    )
    return q, handler, loc_repo, resource_repo, avail_repo, reservations_repo


def test_available_and_repository_filters_include_all_candidates(case):
    q, handler, locs, resources, availability, reservations = case
    assert handler.handle(q).available
    assert locs.calls == [
        {"tenant_id": q.tenant_id, "business_id": q.business_id, "location_id": q.location_id}
    ]
    assert resources.calls == [
        {"tenant_id": q.tenant_id, "business_id": q.business_id, "resource_id": q.resource_id}
    ]
    rules, blocks = availability.calls
    assert rules[1]["tenant_id"] == q.tenant_id and rules[1]["resource_id"] == q.resource_id
    assert rules[1]["range"] == DateRange(date(2026, 3, 28), date(2026, 3, 30))
    assert blocks[1]["location_id"] == q.location_id
    assert reservations.calls[0]["status"] is None
    assert reservations.calls[0]["time_range"] == TimeRange(q.interval.start, q.interval.end)


def test_general_block_and_occupied_reservation_affect_result(case):
    q, handler, _, _, availability, reservations = case
    reservation = Reservation(
        id=ReservationId.generate(),
        tenant_id=q.tenant_id,
        business_id=q.business_id,
        location_id=q.location_id,
        resource_id=q.resource_id,
        customer_id=CustomerId.generate(),
        time_range=TimeRange(q.interval.start, q.interval.end),
        status=ReservationStatus.CHECKED_IN,
    )
    reservations.items = [reservation]
    assert handler.handle(q).reason == AvailabilityReason.RESERVATION_CONFLICT
    availability.blocks = [
        AvailabilityBlock(
            id=AvailabilityBlockId.generate(),
            tenant_id=q.tenant_id,
            location_id=q.location_id,
            blocked_range=DateRange.single(date(2026, 3, 29)),
            reason=BlockReason.HOLIDAY,
        )
    ]
    assert handler.handle(q).reason == AvailabilityReason.BLOCKED


@pytest.mark.parametrize("missing", ["location", "resource"])
def test_missing_location_or_resource_rejected(case, missing):
    q, handler, locs, resources, _, _ = case
    if missing == "location":
        locs.value = None
    else:
        resources.value = None
    with pytest.raises(ApplicationError, match="no encontrad"):
        handler.handle(q)


@pytest.mark.parametrize("field", ["tenant_id", "business_id", "id"])
def test_foreign_location_rejected_before_other_reads(case, field):
    q, handler, locs, resources, availability, _ = case
    locs.value = replace(locs.value, **{field: type(getattr(locs.value, field)).generate()})
    with pytest.raises(ApplicationError, match="fuera del ámbito"):
        handler.handle(q)
    assert not resources.calls and not availability.calls


@pytest.mark.parametrize("field", ["tenant_id", "business_id", "id", "location_id"])
def test_foreign_resource_rejected_before_availability_reads(case, field):
    q, handler, _, resources, availability, _ = case
    resources.value = replace(
        resources.value, **{field: type(getattr(resources.value, field)).generate()}
    )
    with pytest.raises(ApplicationError, match="fuera del ámbito"):
        handler.handle(q)
    assert not availability.calls


def test_closed_location_and_invalid_zone_fail_closed(case):
    q, handler, locs, _, availability, _ = case
    locs.value = replace(locs.value, status=LocationStatus.CLOSED)
    with pytest.raises(ApplicationError, match="no está abierta"):
        handler.handle(q)
    locs.value = replace(locs.value, status=LocationStatus.OPEN, timezone="Invalid/Zone")
    with pytest.raises(ApplicationError, match="Zona horaria"):
        handler.handle(q)
    assert not availability.calls


def test_out_of_scope_reservation_and_rule_are_rejected(case):
    q, handler, _, _, availability, reservations = case
    availability.rules = [replace(availability.rules[0], tenant_id=TenantId.generate())]
    with pytest.raises(InvariantViolationError, match="fuera del"):
        handler.handle(q)
    availability.rules = []
    reservations.items = [
        Reservation(
            id=ReservationId.generate(),
            tenant_id=TenantId.generate(),
            business_id=q.business_id,
            location_id=q.location_id,
            resource_id=q.resource_id,
            customer_id=CustomerId.generate(),
            time_range=TimeRange(q.interval.start, q.interval.end),
        )
    ]
    with pytest.raises(InvariantViolationError, match="fuera del"):
        handler.handle(q)
