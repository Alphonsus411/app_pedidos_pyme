from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest

from universal_business.domain.catalog.entities import Offering
from universal_business.domain.catalog.value_objects import CatalogItemStatus
from universal_business.domain.orders.offering_snapshot import capture_offering_line
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    OfferingId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money


@pytest.fixture
def data() -> dict[str, object]:
    tenant, business, location = TenantId.generate(), BusinessId.generate(), LocationId.generate()
    offering = Offering(
        id=OfferingId.generate(),
        tenant_id=tenant,
        business_id=business,
        name="Servicio",
        status=CatalogItemStatus.ACTIVE,
        location_ids=frozenset({location}),
        base_price=Money("12", "EUR"),
    )
    return dict(
        tenant_id=tenant,
        business_id=business,
        location_id=location,
        offering=offering,
        line_id=uuid4(),
        quantity=Decimal("2"),
        discount=Money(0, "EUR"),
        tax=Money(0, "EUR"),
    )


def test_snapshot_survives_catalog_changes(data: dict[str, object]) -> None:
    line = capture_offering_line(**data)  # type: ignore[arg-type]
    offering = data["offering"]
    assert isinstance(offering, Offering)
    offering.name = "Modificado"
    offering.base_price = Money(20, "EUR")
    assert line.name == "Servicio"
    assert line.unit_price == Money(12, "EUR")
    assert line.total == Money(24, "EUR")


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", TenantId.generate()),
        ("business_id", BusinessId.generate()),
        ("location_id", LocationId.generate()),
        ("tenant_id", None),
        ("offering", None),
    ],
)
def test_scope_rejected(data: dict[str, object], field: str, value: object) -> None:
    data[field] = value
    with pytest.raises(InvariantViolationError):
        capture_offering_line(**data)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "status", [CatalogItemStatus.DRAFT, CatalogItemStatus.INACTIVE, CatalogItemStatus.ARCHIVED]
)
def test_offering_must_be_active(data: dict[str, object], status: CatalogItemStatus) -> None:
    offering = data["offering"]
    assert isinstance(offering, Offering)
    data["offering"] = replace(offering, status=status)
    with pytest.raises(InvariantViolationError):
        capture_offering_line(**data)  # type: ignore[arg-type]


def test_absent_price_rejected_but_free_is_allowed(data: dict[str, object]) -> None:
    offering = data["offering"]
    assert isinstance(offering, Offering)
    data["offering"] = replace(offering, base_price=None)
    with pytest.raises(InvariantViolationError):
        capture_offering_line(**data)  # type: ignore[arg-type]
    data["offering"] = replace(offering, base_price=Money(0, "EUR"))
    assert capture_offering_line(**data).total == Money(0, "EUR")  # type: ignore[arg-type]


def test_business_wide_offering_and_bad_adjustment(data: dict[str, object]) -> None:
    offering = data["offering"]
    assert isinstance(offering, Offering)
    data["offering"] = replace(offering, location_ids=frozenset())
    data["location_id"] = LocationId.generate()
    assert capture_offering_line(**data).name == offering.name  # type: ignore[arg-type]
    data["discount"] = Money(1, "USD")
    with pytest.raises(InvariantViolationError):
        capture_offering_line(**data)  # type: ignore[arg-type]
