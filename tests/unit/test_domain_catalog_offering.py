"""Tests unitarios para dominio catalog: Offering."""

from __future__ import annotations

import types
from decimal import Decimal

import pytest

from universal_business.domain.catalog import (
    Offering,
    OfferingActivated,
    OfferingArchived,
    OfferingPriceChanged,
)
from universal_business.domain.catalog.value_objects import CatalogItemStatus
from universal_business.domain.shared.errors import (
    InvariantViolationError,
)
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    OfferingId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import (
    Money,
    MoneyCurrencyMismatchError,
)


def _make_offering(
    *,
    name: str = "Café Latte",
    base_price: Money | None = None,
    location_ids: frozenset[LocationId] | None = None,
) -> Offering:
    return Offering(
        id=OfferingId.generate(),
        tenant_id=TenantId.generate(),
        business_id=BusinessId.generate(),
        name=name,
        base_price=base_price,
        location_ids=location_ids or frozenset(),
    )


def test_offering_create_valid_default() -> None:
    # Arrange
    tid = TenantId.generate()
    bid = BusinessId.generate()
    oid = OfferingId.generate()

    # Act
    o = Offering(
        id=oid,
        tenant_id=tid,
        business_id=bid,
        name="  Café Mediano  ",
    )

    # Assert
    assert o.id is oid
    assert o.tenant_id is tid
    assert o.business_id is bid
    assert o.name == "Café Mediano"
    assert o.status == CatalogItemStatus.DRAFT
    assert o.category_id is None
    assert o.base_price is None
    assert o.location_ids == frozenset()
    assert isinstance(o.metadata, types.MappingProxyType)
    assert len(o.metadata) == 0


def test_offering_name_empty_stripped_fails() -> None:
    # Arrange
    with pytest.raises(InvariantViolationError) as exc_info:
        # Act
        Offering(
            id=OfferingId.generate(),
            tenant_id=TenantId.generate(),
            business_id=BusinessId.generate(),
            name="   ",
        )

    # Assert
    assert "Offering.name no puede ser vacío" in str(exc_info.value)


def test_offering_requires_tenant_and_business() -> None:
    # Arrange / Act / Assert: Omitting tenant_id (dataclass kw_only)
    with pytest.raises(TypeError):
        Offering(
            id=OfferingId.generate(),
            business_id=BusinessId.generate(),
            name="X",
        )  # type: ignore[call-arg]

    with pytest.raises(TypeError):
        Offering(
            id=OfferingId.generate(),
            tenant_id=TenantId.generate(),
            name="X",
        )  # type: ignore[call-arg]


def test_offering_activate_ok() -> None:
    # Arrange
    o = _make_offering()
    assert o.status == CatalogItemStatus.DRAFT

    # Act
    o.activate()

    # Assert
    assert o.status == CatalogItemStatus.ACTIVE


def test_offering_deactivate_ok() -> None:
    # Arrange
    o = _make_offering()
    o.activate()
    assert o.status == CatalogItemStatus.ACTIVE

    # Act
    o.deactivate()

    # Assert
    assert o.status == CatalogItemStatus.INACTIVE


def test_offering_archive_then_activate_raises() -> None:
    # Arrange
    o = _make_offering()
    o.archive()
    assert o.status == CatalogItemStatus.ARCHIVED

    # Act / Assert
    with pytest.raises(InvariantViolationError) as exc_info:
        o.activate()
    assert "No se puede activar un Offering ARCHIVED" in str(exc_info.value)


def test_offering_archive_then_deactivate_raises() -> None:
    # Arrange
    o = _make_offering()
    o.archive()
    assert o.status == CatalogItemStatus.ARCHIVED

    # Act / Assert
    with pytest.raises(InvariantViolationError) as exc_info:
        o.deactivate()
    assert "No se puede desactivar un Offering ARCHIVED" in str(exc_info.value)


def test_offering_change_base_price_ok_same_currency() -> None:
    # Arrange
    o = _make_offering(base_price=Money("100.00", "USD"))

    # Act
    o.change_base_price(Money("150.50", "USD"))

    # Assert
    assert o.base_price is not None
    assert o.base_price.amount == Decimal("150.5000")
    assert o.base_price.currency == "USD"


def test_offering_change_base_price_currency_mismatch_raises() -> None:
    # Arrange
    o = _make_offering(base_price=Money("100.00", "USD"))

    # Act / Assert
    with pytest.raises(MoneyCurrencyMismatchError) as exc_info:
        o.change_base_price(Money("100.00", "EUR"))
    assert "No se puede cambiar moneda" in str(exc_info.value)
    assert o.base_price is not None
    assert o.base_price.currency == "USD"


def test_offering_change_base_price_from_none_any_currency_ok() -> None:
    # Arrange
    o = _make_offering(base_price=None)

    # Act
    o.change_base_price(Money("200", "DOP"))

    # Assert
    assert o.base_price is not None
    assert o.base_price.amount == Decimal("200.0000")
    assert o.base_price.currency == "DOP"

    # Cambio dentro de la misma moneda debe seguir funcionando
    o.change_base_price(Money("250", "DOP"))
    assert o.base_price.amount == Decimal("250.0000")


def test_offering_location_ids_accepted_frozenset() -> None:
    # Arrange
    loc1 = LocationId.generate()
    loc2 = LocationId.generate()

    # Act
    o = _make_offering(location_ids=frozenset({loc1, loc2}))

    # Assert
    assert isinstance(o.location_ids, frozenset)
    assert len(o.location_ids) == 2
    assert loc1 in o.location_ids
    assert loc2 in o.location_ids


def test_offering_metadata_is_readonly_mapping_proxy() -> None:
    # Arrange
    original = {"sku": "CAF-001", "tags": ["bebida", "caliente"]}

    # Act
    o = Offering(
        id=OfferingId.generate(),
        tenant_id=TenantId.generate(),
        business_id=BusinessId.generate(),
        name="Café",
        metadata=original,
    )

    # Assert
    assert isinstance(o.metadata, types.MappingProxyType)
    assert o.metadata["sku"] == "CAF-001"

    with pytest.raises(TypeError):
        o.metadata["sku"] = "OTRO"  # type: ignore[index]

    with pytest.raises(TypeError):
        del o.metadata["sku"]  # type: ignore[attr-defined]

    # Mutación del dict original NO afecta al metadata del Offering
    original["sku"] = "MUTADO"
    original["nuevo"] = 42
    assert o.metadata["sku"] == "CAF-001"
    assert "nuevo" not in o.metadata


def test_offering_activate_emits_event() -> None:
    # Arrange
    o = _make_offering()

    # Act
    o.activate()

    # Assert
    events = [e for e in o.domain_events if isinstance(e, OfferingActivated)]
    assert len(events) == 1
    ev = events[0]
    assert ev.aggregate_id is o.id
    assert ev.tenant_id is o.tenant_id
    assert ev.business_id is o.business_id


def test_offering_archive_emits_event() -> None:
    # Arrange
    o = _make_offering()

    # Act
    o.archive()

    # Assert
    events = [e for e in o.domain_events if isinstance(e, OfferingArchived)]
    assert len(events) == 1
    ev = events[0]
    assert ev.aggregate_id is o.id
    assert ev.tenant_id is o.tenant_id
    assert ev.business_id is o.business_id


def test_offering_change_base_price_emits_event() -> None:
    # Arrange
    o = _make_offering(base_price=Money("50", "USD"))

    # Act
    o.change_base_price(Money("75.25", "USD"))

    # Assert
    events = [e for e in o.domain_events if isinstance(e, OfferingPriceChanged)]
    assert len(events) == 1
    ev = events[0]
    assert ev.aggregate_id is o.id
    assert ev.tenant_id is o.tenant_id
    assert ev.business_id is o.business_id
    assert ev.new_price_amount == Decimal("75.2500")
    assert ev.currency == "USD"
