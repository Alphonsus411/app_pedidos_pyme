"""Tests unitarios para dominio catalog: OfferingResourceRequirement."""

from __future__ import annotations

import pytest

from universal_business.domain.catalog import OfferingResourceRequirement
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import (
    OfferingId,
    ResourceTypeId,
)


def test_requirement_create_valid_qty_1_default() -> None:
    # Arrange
    oid = OfferingId.generate()
    rtid = ResourceTypeId.generate()

    # Act
    req = OfferingResourceRequirement(
        offering_id=oid,
        resource_type_id=rtid,
    )

    # Assert
    assert req.offering_id is oid
    assert req.resource_type_id is rtid
    assert req.quantity_required == 1
    assert req.required_flag is True


def test_requirement_qty_zero_raises() -> None:
    # Arrange / Act / Assert
    with pytest.raises(InvariantViolationError) as exc_info:
        OfferingResourceRequirement(
            offering_id=OfferingId.generate(),
            resource_type_id=ResourceTypeId.generate(),
            quantity_required=0,
        )
    assert "quantity_required debe ser >= 1" in str(exc_info.value)


def test_requirement_qty_negative_raises() -> None:
    # Arrange / Act / Assert
    with pytest.raises(InvariantViolationError) as exc_info:
        OfferingResourceRequirement(
            offering_id=OfferingId.generate(),
            resource_type_id=ResourceTypeId.generate(),
            quantity_required=-5,
        )
    assert "quantity_required debe ser >= 1" in str(exc_info.value)


def test_requirement_required_flag_false_ok() -> None:
    # Arrange
    oid = OfferingId.generate()
    rtid = ResourceTypeId.generate()

    # Act
    req = OfferingResourceRequirement(
        offering_id=oid,
        resource_type_id=rtid,
        quantity_required=3,
        required_flag=False,
    )

    # Assert
    assert req.offering_id is oid
    assert req.resource_type_id is rtid
    assert req.quantity_required == 3
    assert req.required_flag is False
