"""Tests unitarios para la entidad de dominio Resource (recurso reservable)."""

from __future__ import annotations

import pytest

from universal_business.domain.resources import (
    Resource,
    ResourceActivated,
    ResourceAssignedToLocation,
    ResourceDeactivated,
    ResourceStatus,
)
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    ResourceId,
    ResourceTypeId,
    TenantId,
)


def _make_resource(**kw):
    defaults = dict(
        id=ResourceId.generate(),
        tenant_id=TenantId.generate(),
        business_id=BusinessId.generate(),
        resource_type_id=ResourceTypeId.generate(),
        name="Mesa 1",
    )
    defaults.update(kw)
    return Resource(**defaults)


def test_resource_create_valid_default_location_none() -> None:
    r = _make_resource()
    assert r.location_id is None
    assert r.status == ResourceStatus.ACTIVE
    assert r.name == "Mesa 1"
    assert isinstance(r.id, ResourceId)
    assert isinstance(r.resource_type_id, ResourceTypeId)


def test_resource_create_valid_with_location_and_type() -> None:
    lid = LocationId.generate()
    rtid = ResourceTypeId.generate()
    r = _make_resource(location_id=lid, resource_type_id=rtid, name="Salón Privado")
    assert r.location_id is lid
    assert r.resource_type_id is rtid
    assert r.name == "Salón Privado"


def test_resource_name_empty_raises() -> None:
    with pytest.raises(InvariantViolationError):
        _make_resource(name="")
    with pytest.raises(InvariantViolationError):
        _make_resource(name="   ")


def test_resource_activate_emits_event() -> None:
    r = _make_resource(status=ResourceStatus.INACTIVE)
    n_before = len(r.domain_events)
    r.activate()
    assert r.status == ResourceStatus.ACTIVE
    events_added = r.domain_events[n_before:]
    types = [type(e).__name__ for e in events_added]
    assert "ResourceActivated" in types
    assert any(isinstance(e, ResourceActivated) for e in events_added)


def test_resource_deactivate_from_active_emits_event() -> None:
    r = _make_resource(status=ResourceStatus.ACTIVE)
    n_before = len(r.domain_events)
    r.deactivate()
    assert r.status == ResourceStatus.INACTIVE
    events_added = r.domain_events[n_before:]
    assert any(isinstance(e, ResourceDeactivated) for e in events_added)


def test_resource_archive_then_activate_raises() -> None:
    r = _make_resource(status=ResourceStatus.ACTIVE)
    r.archive()
    assert r.status == ResourceStatus.ARCHIVED
    with pytest.raises(InvariantViolationError):
        r.activate()


def test_resource_assign_to_location_from_none_emits() -> None:
    r = _make_resource(location_id=None)
    n_before = len(r.domain_events)
    new_loc = LocationId.generate()
    r.assign_to_location(new_loc)
    assert r.location_id is new_loc
    events_added = r.domain_events[n_before:]
    assign_events = [e for e in events_added if isinstance(e, ResourceAssignedToLocation)]
    assert len(assign_events) == 1
    assert assign_events[0].old_location_id is None
    assert assign_events[0].new_location_id is new_loc


def test_resource_assign_to_same_location_no_event() -> None:
    loc = LocationId.generate()
    r = _make_resource(location_id=loc)
    n_before = len(r.domain_events)
    r.assign_to_location(loc)
    n_after = len(r.domain_events)
    assert n_after == n_before


def test_resource_unassign_from_location_to_none_emits() -> None:
    loc = LocationId.generate()
    r = _make_resource(location_id=loc)
    n_before = len(r.domain_events)
    r.assign_to_location(None)
    assert r.location_id is None
    events_added = r.domain_events[n_before:]
    assign_events = [e for e in events_added if isinstance(e, ResourceAssignedToLocation)]
    assert len(assign_events) == 1
    assert assign_events[0].old_location_id is loc
    assert assign_events[0].new_location_id is None


def test_resource_tenant_and_business_required() -> None:
    with pytest.raises(TypeError):
        Resource(
            id=ResourceId.generate(),
            # tenant_id omitido → dataclass required sin default
            business_id=BusinessId.generate(),
            resource_type_id=ResourceTypeId.generate(),
            name="X",
        )
    with pytest.raises(TypeError):
        Resource(
            id=ResourceId.generate(),
            tenant_id=TenantId.generate(),
            # business_id omitido → dataclass required sin default
            resource_type_id=ResourceTypeId.generate(),
            name="X",
        )
    with pytest.raises(InvariantViolationError):
        Resource(
            id=ResourceId.generate(),
            tenant_id=TenantId.generate(),
            business_id=BusinessId.generate(),
            resource_type_id="not-an-id",  # type: ignore[arg-type]
            name="X",
        )
