"""Queries concretas para el módulo Resources (Gate 0.3).

Todas las queries heredan de :class:`Query` (frozen, kw_only=True) y llevan
``tenant_id`` + ``business_id`` explícitos. Semánticamente de solo lectura.
"""

from __future__ import annotations

from dataclasses import dataclass

from universal_business.application.messaging.queries import Query
from universal_business.domain.catalog.value_objects import CatalogItemStatus
from universal_business.domain.resources.value_objects import ResourceStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    ResourceId,
    ResourceTypeId,
    TenantId,
)


@dataclass(frozen=True, kw_only=True)
class GetResource(Query):
    tenant_id: TenantId
    business_id: BusinessId
    resource_id: ResourceId


@dataclass(frozen=True, kw_only=True)
class ListResourcesByBusiness(Query):
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId | None = None
    status: ResourceStatus | None = None
    resource_type_id: ResourceTypeId | None = None


@dataclass(frozen=True, kw_only=True)
class ListResourcesByLocation(Query):
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    resource_type_id: ResourceTypeId | None = None


@dataclass(frozen=True, kw_only=True)
class ListActiveResources(Query):
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId | None = None
    resource_type_id: ResourceTypeId | None = None


@dataclass(frozen=True, kw_only=True)
class ListResourceTypesByBusiness(Query):
    tenant_id: TenantId
    business_id: BusinessId
    status: CatalogItemStatus | None = None


__all__ = [
    "GetResource",
    "ListResourcesByBusiness",
    "ListResourcesByLocation",
    "ListActiveResources",
    "ListResourceTypesByBusiness",
]
