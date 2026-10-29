import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from universal_business.application.availability.handlers import EvaluateResourceAvailabilityHandler
from universal_business.application.availability.queries import EvaluateResourceAvailability
from universal_business.domain.availability.entities import AvailabilityBlock, AvailabilityRule
from universal_business.domain.availability.evaluation import AvailabilityReason
from universal_business.domain.availability.value_objects import BlockReason
from universal_business.domain.business.entities import Location
from universal_business.domain.business.value_objects import Address, LocationStatus, OperatingHours
from universal_business.domain.reservations.interval import ReservationInterval
from universal_business.domain.resources.entities import Resource
from universal_business.domain.shared.value_objects.ids import (
    AvailabilityBlockId,
    AvailabilityRuleId,
    BusinessId,
    LocationId,
    ResourceId,
    ResourceTypeId,
    TenantId,
)
from universal_business.domain.shared.value_objects.temporal import DateRange, TimeRange
from universal_business.infrastructure.sqlite_availability import (
    SqliteAvailabilityRepository,
    create_sqlite_availability_schema,
)


@pytest.fixture
def context():
    connection = sqlite3.connect(":memory:")
    create_sqlite_availability_schema(connection)
    repo = SqliteAvailabilityRepository(connection)
    tenant, location, resource = TenantId.generate(), LocationId.generate(), ResourceId.generate()
    day = date(2026, 3, 29)
    start = datetime(2026, 3, 29, 9, tzinfo=UTC)
    rule = AvailabilityRule(
        id=AvailabilityRuleId.generate(),
        tenant_id=tenant,
        location_id=location,
        effective_range=DateRange.single(day),
        time_ranges=[TimeRange(start, start + timedelta(hours=1))],
    )
    block = AvailabilityBlock(
        id=AvailabilityBlockId.generate(),
        tenant_id=tenant,
        location_id=location,
        blocked_range=DateRange.single(day),
        reason=BlockReason.HOLIDAY,
        note="Cierre",
    )
    yield connection, repo, rule, block, resource
    connection.close()


def test_scoped_queries_include_general_and_resource_rules_and_boundaries(context):
    connection, repo, rule, block, resource = context
    specific = replace(rule, id=AvailabilityRuleId.generate(), resource_id=resource)
    other = replace(rule, id=AvailabilityRuleId.generate(), resource_id=ResourceId.generate())
    foreign = replace(rule, id=AvailabilityRuleId.generate(), tenant_id=TenantId.generate())
    specific_block = replace(
        block, id=AvailabilityBlockId.generate(), resource_id=ResourceId.generate()
    )
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        for item in (rule, specific, other, foreign):
            repo.save_rule(item)
        repo.save_block(block)
        repo.save_block(specific_block)
    scope = dict(tenant_id=rule.tenant_id, location_id=rule.location_id, range=rule.effective_range)
    assert set(x.id for x in repo.list_rules_for_resource(**scope, resource_id=resource)) == {
        rule.id,
        specific.id,
    }
    assert set(x.id for x in repo.list_rules_for_resource(**scope)) == {
        rule.id,
        specific.id,
        other.id,
    }
    assert set(x.id for x in repo.list_blocks(**scope)) == {block.id, specific_block.id}
    assert (
        repo.list_rules_for_resource(**scope, resource_id=resource)[0].time_ranges
        == rule.time_ranges
    )
    assert repo.list_blocks(**scope)[0].note == "Cierre"
    outside = DateRange.single(date(2026, 3, 30))
    assert (
        repo.list_rules_for_resource(
            tenant_id=rule.tenant_id, location_id=rule.location_id, range=outside
        )
        == []
    )


def test_transaction_rollback_and_immutable_location(context):
    connection, repo, rule, block, _ = context
    with pytest.raises(RuntimeError, match="transacción"):
        repo.save_rule(rule)
    with pytest.raises(RuntimeError, match="rollback"):
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            repo.save_rule(rule)
            repo.save_block(block)
            raise RuntimeError("rollback")
    scope = dict(tenant_id=rule.tenant_id, location_id=rule.location_id, range=rule.effective_range)
    assert repo.list_rules_for_resource(**scope) == []
    assert repo.list_blocks(**scope) == []
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        repo.save_rule(rule)
    with pytest.raises(ValueError, match="ubicación"):
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            repo.save_rule(replace(rule, location_id=LocationId.generate()))
    assert len(repo.list_rules_for_resource(**scope)) == 1


def test_corrupt_interval_encoding_fails_closed(context):
    connection, repo, rule, _, _ = context
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        repo.save_rule(rule)
        connection.execute(
            "UPDATE availability_rules SET intervals=?", ('{"version":true,"intervals":[]}',)
        )
    with pytest.raises(ValueError, match="Intervalos"):
        repo.list_rules_for_resource(
            tenant_id=rule.tenant_id, location_id=rule.location_id, range=rule.effective_range
        )


def test_real_availability_handler_reads_persisted_rules_and_blocks(context):
    connection, repo, rule, block, resource_id = context
    business = BusinessId.generate()
    location = Location(
        id=rule.location_id,
        tenant_id=rule.tenant_id,
        business_id=business,
        name="Local",
        address=Address(country_code="ES"),
        timezone="UTC",
        operating_hours=OperatingHours(),
        status=LocationStatus.OPEN,
    )
    resource = Resource(
        id=resource_id,
        tenant_id=rule.tenant_id,
        business_id=business,
        location_id=rule.location_id,
        resource_type_id=ResourceTypeId.generate(),
        name="Sala",
        capacity=2,
    )

    class Lookup:
        def __init__(self, value):
            self.value = value

        def get(self, **kwargs):
            return self.value

    class Reservations:
        def list_for_resource_in_range(self, **kwargs):
            return []

    handler = EvaluateResourceAvailabilityHandler(
        locations=Lookup(location),
        resources=Lookup(resource),
        availability=repo,
        reservations=Reservations(),
    )
    query = EvaluateResourceAvailability(
        tenant_id=rule.tenant_id,
        business_id=business,
        location_id=rule.location_id,
        resource_id=resource_id,
        interval=ReservationInterval(rule.time_ranges[0].start, rule.time_ranges[0].end),
        party_size=2,
    )
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        repo.save_rule(rule)
    assert handler.handle(query).available
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        repo.save_block(block)
    assert handler.handle(query).reason == AvailabilityReason.BLOCKED
