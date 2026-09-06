"""Tests unitarios para dominio catalog: CatalogCategory."""

from __future__ import annotations

import pytest

from universal_business.domain.catalog import CatalogCategory
from universal_business.domain.catalog.value_objects import CatalogItemStatus
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CatalogCategoryId,
    TenantId,
)


def test_category_create_valid() -> None:
    # Arrange
    cid = CatalogCategoryId.generate()
    tid = TenantId.generate()
    bid = BusinessId.generate()

    # Act
    c = CatalogCategory(
        id=cid,
        tenant_id=tid,
        business_id=bid,
        name="  Bebidas Calientes  ",
        description="Bebidas calientes variadas",
    )

    # Assert
    assert c.id is cid
    assert c.tenant_id is tid
    assert c.business_id is bid
    assert c.name == "Bebidas Calientes"
    assert c.description == "Bebidas calientes variadas"
    assert c.status == CatalogItemStatus.DRAFT
    assert c.parent_category_id is None


def test_category_name_empty_fails() -> None:
    # Arrange / Act / Assert
    with pytest.raises(InvariantViolationError) as exc_info:
        CatalogCategory(
            id=CatalogCategoryId.generate(),
            tenant_id=TenantId.generate(),
            business_id=BusinessId.generate(),
            name="   ",
        )
    assert "CatalogCategory.name no puede ser vacío" in str(exc_info.value)


def test_category_self_parent_raises() -> None:
    # Arrange
    cid = CatalogCategoryId.generate()

    # Act / Assert
    with pytest.raises(InvariantViolationError) as exc_info:
        CatalogCategory(
            id=cid,
            tenant_id=TenantId.generate(),
            business_id=BusinessId.generate(),
            name="Café",
            parent_category_id=cid,
        )
    assert "Category no puede ser su propio padre" in str(exc_info.value)


def test_category_hierarchy_two_levels_ok() -> None:
    # Arrange
    parent_id = CatalogCategoryId.generate()
    child_id = CatalogCategoryId.generate()
    tid = TenantId.generate()
    bid = BusinessId.generate()

    # Act
    parent = CatalogCategory(
        id=parent_id,
        tenant_id=tid,
        business_id=bid,
        name="Bebidas",
    )
    child = CatalogCategory(
        id=child_id,
        tenant_id=tid,
        business_id=bid,
        name="Café",
        parent_category_id=parent_id,
    )

    # Assert
    assert parent.parent_category_id is None
    assert child.parent_category_id is parent_id
    assert parent.id != child.id


def test_category_activate_deactivate_archive() -> None:
    # Arrange
    c = CatalogCategory(
        id=CatalogCategoryId.generate(),
        tenant_id=TenantId.generate(),
        business_id=BusinessId.generate(),
        name="Test",
    )
    assert c.status == CatalogItemStatus.DRAFT

    # Act / Assert: activate
    c.activate()
    assert c.status == CatalogItemStatus.ACTIVE

    # Act / Assert: deactivate
    c.deactivate()
    assert c.status == CatalogItemStatus.INACTIVE

    # Act / Assert: re-activate
    c.activate()
    assert c.status == CatalogItemStatus.ACTIVE

    # Act / Assert: archive
    c.archive()
    assert c.status == CatalogItemStatus.ARCHIVED

    # Act / Assert: no se puede activar desde archived
    with pytest.raises(InvariantViolationError) as exc_info:
        c.activate()
    assert "No se puede activar una CatalogCategory ARCHIVED" in str(exc_info.value)

    # Act / Assert: no se puede desactivar desde archived
    with pytest.raises(InvariantViolationError) as exc_info:
        c.deactivate()
    assert "No se puede desactivar una CatalogCategory ARCHIVED" in str(exc_info.value)
