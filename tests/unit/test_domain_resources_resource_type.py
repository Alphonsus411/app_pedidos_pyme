"""Tests unitarios para la entidad de dominio ResourceTypeEntity (catálogo de recursos)."""

from __future__ import annotations

import pytest

from universal_business.domain.catalog.value_objects import CatalogItemStatus
from universal_business.domain.resources import ResourceTypeEntity
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    ResourceTypeId,
    TenantId,
)


def _make_rt(**kw):
    defaults = dict(
        id=ResourceTypeId.generate(),
        tenant_id=TenantId.generate(),
        business_id=BusinessId.generate(),
        name="Mesa",
    )
    defaults.update(kw)
    return ResourceTypeEntity(**defaults)


def test_resource_type_entity_create_valid_default_status_DRAFT() -> None:
    rt = _make_rt(name="Salones")
    assert rt.name == "Salones"
    assert rt.status == CatalogItemStatus.DRAFT
    assert isinstance(rt.id, ResourceTypeId)
    assert isinstance(rt.tenant_id, TenantId)
    assert isinstance(rt.business_id, BusinessId)


def test_resource_type_entity_name_empty_strip_fails() -> None:
    with pytest.raises(InvariantViolationError):
        _make_rt(name="")
    with pytest.raises(InvariantViolationError):
        _make_rt(name="   ")
    with pytest.raises(InvariantViolationError):
        _make_rt(name="\t\n")


def test_resource_type_entity_activate_ok() -> None:
    rt = _make_rt()
    assert rt.status == CatalogItemStatus.DRAFT
    rt.activate()
    assert rt.status == CatalogItemStatus.ACTIVE
    rt2 = _make_rt(status=CatalogItemStatus.INACTIVE)
    rt2.activate()
    assert rt2.status == CatalogItemStatus.ACTIVE


def test_resource_type_entity_deactivate_ok() -> None:
    rt = _make_rt(status=CatalogItemStatus.ACTIVE)
    rt.deactivate()
    assert rt.status == CatalogItemStatus.INACTIVE
    rt2 = _make_rt()  # DRAFT
    rt2.deactivate()
    assert rt2.status == CatalogItemStatus.INACTIVE


def test_resource_type_entity_archive_then_activate_raises_invariant() -> None:
    rt = _make_rt(status=CatalogItemStatus.ACTIVE)
    rt.archive()
    assert rt.status == CatalogItemStatus.ARCHIVED
    with pytest.raises(InvariantViolationError):
        rt.activate()
    with pytest.raises(InvariantViolationError):
        rt.deactivate()
