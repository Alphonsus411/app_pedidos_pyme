"""Queries concretas para el subpackage Catalog (Gate 0.3).

Todas las queries son frozen dataclasses (inmutables), ``kw_only=True``,
y llevan ``tenant_id`` + ``business_id`` explícitos. Son operaciones de
solo lectura (no emiten DomainEvent).
"""

from __future__ import annotations

from dataclasses import dataclass

from universal_business.application.messaging import Query
from universal_business.domain.catalog.value_objects import CatalogItemStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CatalogCategoryId,
    LocationId,
    OfferingId,
    TenantId,
)


@dataclass(frozen=True, kw_only=True)
class GetOffering(Query):
    tenant_id: TenantId
    business_id: BusinessId
    offering_id: OfferingId


@dataclass(frozen=True, kw_only=True)
class ListOfferingsByBusiness(Query):
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId | None = None
    status: CatalogItemStatus | None = None


@dataclass(frozen=True, kw_only=True)
class ListOfferingsByLocation(Query):
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId


@dataclass(frozen=True, kw_only=True)
class ListActiveOfferings(Query):
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId | None = None


@dataclass(frozen=True, kw_only=True)
class ListCategoriesByBusiness(Query):
    tenant_id: TenantId
    business_id: BusinessId
    status: CatalogItemStatus | None = None
    parent_category_id: CatalogCategoryId | None = None


__all__ = [
    "GetOffering",
    "ListOfferingsByBusiness",
    "ListOfferingsByLocation",
    "ListActiveOfferings",
    "ListCategoriesByBusiness",
]
