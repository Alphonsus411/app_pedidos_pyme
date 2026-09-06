"""Aggregado mínimo CatalogItem (Entrega 0.1 skeleton).

Nada de reglas de pricing ni stock — FASE 1 lo implementa.
"""

from __future__ import annotations

import types
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from universal_business.domain.catalog.events import (
    OfferingActivated,
    OfferingArchived,
    OfferingDeactivated,
    OfferingPriceChanged,
)
from universal_business.domain.catalog.value_objects import CatalogItemStatus, CatalogItemType
from universal_business.domain.shared.base import BaseEntity
from universal_business.domain.shared.errors import (
    InvariantViolationError,
    MoneyCurrencyMismatchError,
)
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CatalogCategoryId,
    CatalogItemId,
    LocationId,
    OfferingId,
    ResourceTypeId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money


@dataclass(kw_only=True)
class CatalogItem(BaseEntity[CatalogItemId]):
    """Ítem catálogo genérico (producto físico / servicio / combo / digital)."""

    tenant_id: TenantId
    business_id: BusinessId
    name: str
    type: CatalogItemType
    status: CatalogItemStatus = CatalogItemStatus.DRAFT
    location_id: LocationId | None = None  # OPCIONAL: catálogo por business entero si None
    sku: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.name, str) or not self.name.strip():
            raise InvariantViolationError("CatalogItem.name no puede ser vacío")
        object.__setattr__(self, "name", self.name.strip())
        if not isinstance(self.type, CatalogItemType):
            raise InvariantViolationError("CatalogItem.type debe ser CatalogItemType")
        if not isinstance(self.status, CatalogItemStatus):
            raise InvariantViolationError("CatalogItem.status debe ser CatalogItemStatus")


@dataclass(kw_only=True)
class Offering(BaseEntity[OfferingId]):
    """Oferta comercial (producto/servicio vendible)."""

    id: OfferingId
    tenant_id: TenantId
    business_id: BusinessId
    name: str
    description: str | None = None
    status: CatalogItemStatus = CatalogItemStatus.DRAFT
    category_id: CatalogCategoryId | None = None
    base_price: Money | None = None
    location_ids: frozenset[LocationId] = field(default_factory=frozenset)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.name, str) or not self.name.strip():
            raise InvariantViolationError("Offering.name no puede ser vacío")
        object.__setattr__(self, "name", self.name.strip())
        if not isinstance(self.status, CatalogItemStatus):
            raise InvariantViolationError("Offering.status debe ser CatalogItemStatus")
        for loc_id in self.location_ids:
            if not isinstance(loc_id, LocationId):
                raise InvariantViolationError(
                    f"Offering.location_ids debe contener solo LocationId, encontrado: {type(loc_id).__name__}"
                )
        if not isinstance(self.metadata, Mapping):
            raise InvariantViolationError("Offering.metadata debe ser Mapping")
        if not isinstance(self.metadata, types.MappingProxyType):
            frozen_md = types.MappingProxyType(dict(self.metadata))
            object.__setattr__(self, "metadata", frozen_md)

    def activate(self) -> None:
        if self.status == CatalogItemStatus.ARCHIVED:
            raise InvariantViolationError("No se puede activar un Offering ARCHIVED")
        object.__setattr__(self, "status", CatalogItemStatus.ACTIVE)
        self.touch()
        self.add_domain_event(
            OfferingActivated(
                aggregate_id=self.id,
                tenant_id=self.tenant_id,
                business_id=self.business_id,
            )
        )

    def deactivate(self) -> None:
        if self.status == CatalogItemStatus.ARCHIVED:
            raise InvariantViolationError("No se puede desactivar un Offering ARCHIVED")
        object.__setattr__(self, "status", CatalogItemStatus.INACTIVE)
        self.touch()
        self.add_domain_event(
            OfferingDeactivated(
                aggregate_id=self.id,
                tenant_id=self.tenant_id,
                business_id=self.business_id,
            )
        )

    def archive(self) -> None:
        object.__setattr__(self, "status", CatalogItemStatus.ARCHIVED)
        self.touch()
        self.add_domain_event(
            OfferingArchived(
                aggregate_id=self.id,
                tenant_id=self.tenant_id,
                business_id=self.business_id,
            )
        )

    def change_base_price(self, new_price: Money) -> None:
        if self.base_price is not None and self.base_price.currency != new_price.currency:
            raise MoneyCurrencyMismatchError(
                f"No se puede cambiar moneda: {self.base_price.currency} -> {new_price.currency}"
            )
        old_amount: Decimal | None = self.base_price.amount if self.base_price is not None else None
        object.__setattr__(self, "base_price", new_price)
        self.touch()
        self.add_domain_event(
            OfferingPriceChanged(
                aggregate_id=self.id,
                tenant_id=self.tenant_id,
                business_id=self.business_id,
                new_price_amount=new_price.amount,
                currency=str(new_price.currency),
                metadata={
                    "old_amount": str(old_amount) if old_amount is not None else None,
                    "new_amount": str(new_price.amount),
                    "currency": str(new_price.currency),
                },
            )
        )


@dataclass(kw_only=True)
class CatalogCategory(BaseEntity[CatalogCategoryId]):
    """Categoría de catálogo (jerárquica)."""

    id: CatalogCategoryId
    tenant_id: TenantId
    business_id: BusinessId
    name: str
    description: str | None = None
    status: CatalogItemStatus = CatalogItemStatus.DRAFT
    parent_category_id: CatalogCategoryId | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.name, str) or not self.name.strip():
            raise InvariantViolationError("CatalogCategory.name no puede ser vacío")
        object.__setattr__(self, "name", self.name.strip())
        if not isinstance(self.status, CatalogItemStatus):
            raise InvariantViolationError("CatalogCategory.status debe ser CatalogItemStatus")
        if self.parent_category_id is not None and self.id == self.parent_category_id:
            raise InvariantViolationError("Category no puede ser su propio padre")
        if not isinstance(self.metadata, Mapping):
            raise InvariantViolationError("CatalogCategory.metadata debe ser Mapping")
        if not isinstance(self.metadata, types.MappingProxyType):
            frozen_md = types.MappingProxyType(dict(self.metadata))
            object.__setattr__(self, "metadata", frozen_md)

    def activate(self) -> None:
        if self.status == CatalogItemStatus.ARCHIVED:
            raise InvariantViolationError("No se puede activar una CatalogCategory ARCHIVED")
        object.__setattr__(self, "status", CatalogItemStatus.ACTIVE)
        self.touch()

    def deactivate(self) -> None:
        if self.status == CatalogItemStatus.ARCHIVED:
            raise InvariantViolationError("No se puede desactivar una CatalogCategory ARCHIVED")
        object.__setattr__(self, "status", CatalogItemStatus.INACTIVE)
        self.touch()

    def archive(self) -> None:
        object.__setattr__(self, "status", CatalogItemStatus.ARCHIVED)
        self.touch()


@dataclass(frozen=True, kw_only=True)
class OfferingResourceRequirement:
    """Requisito de recursos para ofrecer un Offering."""

    offering_id: OfferingId
    resource_type_id: ResourceTypeId
    quantity_required: int = 1
    required_flag: bool = True

    def __post_init__(self) -> None:
        if self.quantity_required < 1:
            raise InvariantViolationError("quantity_required debe ser >= 1")


__all__ = [
    "CatalogItem",
    "Offering",
    "CatalogCategory",
    "OfferingResourceRequirement",
]
