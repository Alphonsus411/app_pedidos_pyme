"""Eventos de dominio para módulo Catalog."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CatalogCategoryId,
    OfferingId,
    TenantId,
)


@dataclass(frozen=True, kw_only=True)
class OfferingCreated(DomainEvent):
    aggregate_id: OfferingId
    tenant_id: TenantId
    business_id: BusinessId
    aggregate_type: str = "Offering"
    name: str
    category_id: CatalogCategoryId | None = None


@dataclass(frozen=True, kw_only=True)
class OfferingActivated(DomainEvent):
    aggregate_id: OfferingId
    tenant_id: TenantId
    business_id: BusinessId
    aggregate_type: str = "Offering"


@dataclass(frozen=True, kw_only=True)
class OfferingDeactivated(DomainEvent):
    aggregate_id: OfferingId
    tenant_id: TenantId
    business_id: BusinessId
    aggregate_type: str = "Offering"


@dataclass(frozen=True, kw_only=True)
class OfferingArchived(DomainEvent):
    aggregate_id: OfferingId
    tenant_id: TenantId
    business_id: BusinessId
    aggregate_type: str = "Offering"


@dataclass(frozen=True, kw_only=True)
class OfferingPriceChanged(DomainEvent):
    aggregate_id: OfferingId
    tenant_id: TenantId
    business_id: BusinessId
    aggregate_type: str = "Offering"
    new_price_amount: Decimal
    currency: str


@dataclass(frozen=True, kw_only=True)
class CatalogCategoryCreated(DomainEvent):
    aggregate_id: CatalogCategoryId
    tenant_id: TenantId
    business_id: BusinessId
    aggregate_type: str = "CatalogCategory"


__all__ = [
    "OfferingCreated",
    "OfferingActivated",
    "OfferingDeactivated",
    "OfferingArchived",
    "OfferingPriceChanged",
    "CatalogCategoryCreated",
]
