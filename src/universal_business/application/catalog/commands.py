"""Commands concretos para el subpackage Catalog (Gate 0.3).

Todos los commands son frozen dataclasses (inmutables), ``kw_only=True``,
y llevan ``tenant_id`` + ``business_id`` explícitos en cada operación que
afecta a entidades tenant-owned. Las operaciones de creación llevan
``idempotency_key`` opcional para garantizar idempotencia a nivel de
aplicación vía :class:`IdempotencyStore`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from universal_business.application.idempotency import IdempotencyKey
from universal_business.application.messaging import Command
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CatalogCategoryId,
    LocationId,
    OfferingId,
    TenantId,
)

if TYPE_CHECKING:
    from universal_business.domain.shared.value_objects.money import Currency


@dataclass(frozen=True, kw_only=True)
class CreateOffering(Command):
    tenant_id: TenantId
    business_id: BusinessId
    offering_id: OfferingId
    name: str
    description: str | None = None
    category_id: CatalogCategoryId | None = None
    base_price: Decimal | None = None
    currency: str | Currency | None = None
    location_ids: frozenset[LocationId] | None = None
    idempotency_key: IdempotencyKey | None = None


@dataclass(frozen=True, kw_only=True)
class ActivateOffering(Command):
    tenant_id: TenantId
    business_id: BusinessId
    offering_id: OfferingId


@dataclass(frozen=True, kw_only=True)
class DeactivateOffering(Command):
    tenant_id: TenantId
    business_id: BusinessId
    offering_id: OfferingId


@dataclass(frozen=True, kw_only=True)
class ArchiveOffering(Command):
    tenant_id: TenantId
    business_id: BusinessId
    offering_id: OfferingId


@dataclass(frozen=True, kw_only=True)
class ChangeOfferingPrice(Command):
    tenant_id: TenantId
    business_id: BusinessId
    offering_id: OfferingId
    new_base_price_amount: Decimal
    new_currency: str | Currency


@dataclass(frozen=True, kw_only=True)
class CreateCatalogCategory(Command):
    tenant_id: TenantId
    business_id: BusinessId
    category_id: CatalogCategoryId
    name: str
    description: str | None = None
    parent_category_id: CatalogCategoryId | None = None
    idempotency_key: IdempotencyKey | None = None


__all__ = [
    "CreateOffering",
    "ActivateOffering",
    "DeactivateOffering",
    "ArchiveOffering",
    "ChangeOfferingPrice",
    "CreateCatalogCategory",
]
