"""Puertos repositorio para Resources."""

from __future__ import annotations

from typing import Protocol

from universal_business.domain.resources.entities import Resource
from universal_business.domain.resources.value_objects import ResourceStatus, ResourceType
from universal_business.domain.shared.value_objects.ids import (
    LocationId,
    ResourceId,
    TenantId,
)


class IResourceRepository(Protocol):
    def get(self, resource_id: ResourceId) -> Resource | None: ...
    def save(self, resource: Resource) -> None: ...
    def list_by_location(
        self,
        *,
        tenant_id: TenantId,
        location_id: LocationId,
        status: ResourceStatus | None = None,
        resource_type: ResourceType | None = None,
    ) -> list[Resource]: ...


__all__ = ["IResourceRepository"]
