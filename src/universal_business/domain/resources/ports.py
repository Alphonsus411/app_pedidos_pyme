"""Puertos repositorio para Resources (Hardening Gate 0.1-RC1).

Resource pertenece a Location → Business → Tenant. Tiene location_id obligatorio.
"""

from __future__ import annotations

from typing import Protocol

from universal_business.domain.catalog.value_objects import CatalogItemStatus
from universal_business.domain.resources.entities import (
    Resource,
)
from universal_business.domain.resources.entities import (
    ResourceType as ResourceTypeEntity,
)
from universal_business.domain.resources.value_objects import ResourceStatus, ResourceType
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    ResourceId,
    ResourceTypeId,
    TenantId,
)


class IResourceRepository(Protocol):
    def get(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        resource_id: ResourceId,
    ) -> Resource | None: ...
    def save(self, resource: Resource, /) -> None: ...
    def list_by_location(
        self,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId,
        status: ResourceStatus | None = None,
        resource_type: ResourceType | None = None,
        resource_type_id: ResourceTypeId | None = None,
    ) -> list[Resource]: ...
    def list_by_business(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId | None = None,
        status: ResourceStatus | None = None,
        resource_type_id: ResourceTypeId | None = None,
    ) -> list[Resource]: ...
    def list_active(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId | None = None,
        resource_type_id: ResourceTypeId | None = None,
    ) -> list[Resource]: ...


class IResourceTypeRepository(Protocol):
    def get(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        resource_type_id: ResourceTypeId,
    ) -> ResourceTypeEntity | None: ...
    def save(self, resource_type: ResourceTypeEntity, /) -> None: ...
    def list_by_business(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        status: CatalogItemStatus | None = None,
    ) -> list[ResourceTypeEntity]: ...


__all__ = ["IResourceRepository", "IResourceTypeRepository"]
