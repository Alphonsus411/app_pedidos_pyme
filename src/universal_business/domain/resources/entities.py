"""Aggregados Resource y ResourceType (catálogo configurable de recursos)."""

from __future__ import annotations

import types
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from universal_business.domain.catalog.value_objects import CatalogItemStatus
from universal_business.domain.resources.events import (
    ResourceActivated,
    ResourceArchived,
    ResourceAssignedToLocation,
    ResourceCreated,
    ResourceDeactivated,
    ResourceTypeCreated,
)
from universal_business.domain.resources.value_objects import ResourceStatus
from universal_business.domain.shared.base import BaseEntity
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    ResourceId,
    ResourceTypeId,
    TenantId,
)


@dataclass(kw_only=True)
class ResourceType(BaseEntity[ResourceTypeId]):
    """Catálogo configurable de tipos de recurso (agregado root).

    NO confundir con ResourceType(StrEnum) legacy de value_objects.py.
    Ésta es una entidad persistente y configurable por tenant/business.
    """

    id: ResourceTypeId
    tenant_id: TenantId
    business_id: BusinessId
    name: str
    description: str | None = None
    status: CatalogItemStatus = CatalogItemStatus.DRAFT
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.name, str) or not self.name.strip():
            raise InvariantViolationError("ResourceType.name no puede ser vacío")
        object.__setattr__(self, "name", self.name.strip())
        if not isinstance(self.status, CatalogItemStatus):
            raise InvariantViolationError("ResourceType.status debe ser CatalogItemStatus")
        if not isinstance(self.metadata, Mapping):
            raise InvariantViolationError("ResourceType.metadata debe ser Mapping")
        if not isinstance(self.metadata, types.MappingProxyType):
            frozen_md = types.MappingProxyType(dict(self.metadata))
            object.__setattr__(self, "metadata", frozen_md)
        self.add_domain_event(
            ResourceTypeCreated(
                aggregate_id=self.id,
                tenant_id=self.tenant_id,
                business_id=self.business_id,
            )
        )

    def activate(self) -> None:
        if self.status == CatalogItemStatus.ARCHIVED:
            raise InvariantViolationError("No se puede activar un ResourceType ARCHIVED")
        object.__setattr__(self, "status", CatalogItemStatus.ACTIVE)
        self.touch()

    def deactivate(self) -> None:
        if self.status == CatalogItemStatus.ARCHIVED:
            raise InvariantViolationError("No se puede desactivar un ResourceType ARCHIVED")
        object.__setattr__(self, "status", CatalogItemStatus.INACTIVE)
        self.touch()

    def archive(self) -> None:
        object.__setattr__(self, "status", CatalogItemStatus.ARCHIVED)
        self.touch()


@dataclass(kw_only=True)
class Resource(BaseEntity[ResourceId]):
    """Recurso reservable atómico. Pertenencia a Location opcional (business-wide si None)."""

    tenant_id: TenantId
    business_id: BusinessId
    resource_type_id: ResourceTypeId
    name: str
    status: ResourceStatus = ResourceStatus.ACTIVE
    location_id: LocationId | None = None
    capacity: int | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.name, str) or not self.name.strip():
            raise InvariantViolationError("Resource.name no puede ser vacío")
        object.__setattr__(self, "name", self.name.strip())
        if not isinstance(self.resource_type_id, ResourceTypeId):
            raise InvariantViolationError("Resource.resource_type_id debe ser ResourceTypeId")
        if not isinstance(self.status, ResourceStatus):
            raise InvariantViolationError("Resource.status debe ser ResourceStatus")
        if self.capacity is not None and self.capacity < 0:
            raise InvariantViolationError("Resource.capacity no puede ser negativo")
        self.add_domain_event(
            ResourceCreated(
                aggregate_id=self.id,
                tenant_id=self.tenant_id,
                business_id=self.business_id,
                resource_type_id=self.resource_type_id,
                location_id=self.location_id,
            )
        )

    def activate(self) -> None:
        if self.status == ResourceStatus.ARCHIVED:
            raise InvariantViolationError("No se puede activar un Resource ARCHIVED")
        object.__setattr__(self, "status", ResourceStatus.ACTIVE)
        self.touch()
        self.add_domain_event(
            ResourceActivated(
                aggregate_id=self.id,
                tenant_id=self.tenant_id,
                business_id=self.business_id,
                location_id=self.location_id,
            )
        )

    def deactivate(self) -> None:
        object.__setattr__(self, "status", ResourceStatus.INACTIVE)
        self.touch()
        self.add_domain_event(
            ResourceDeactivated(
                aggregate_id=self.id,
                tenant_id=self.tenant_id,
                business_id=self.business_id,
                location_id=self.location_id,
            )
        )

    def archive(self) -> None:
        object.__setattr__(self, "status", ResourceStatus.ARCHIVED)
        self.touch()
        self.add_domain_event(
            ResourceArchived(
                aggregate_id=self.id,
                tenant_id=self.tenant_id,
                business_id=self.business_id,
                location_id=self.location_id,
            )
        )

    def assign_to_location(self, new_location_id: LocationId | None) -> None:
        old_location_id = self.location_id
        object.__setattr__(self, "location_id", new_location_id)
        self.touch()
        if old_location_id != new_location_id:
            self.add_domain_event(
                ResourceAssignedToLocation(
                    aggregate_id=self.id,
                    tenant_id=self.tenant_id,
                    business_id=self.business_id,
                    old_location_id=old_location_id,
                    new_location_id=new_location_id,
                    metadata={
                        "old_location": str(old_location_id)
                        if old_location_id is not None
                        else None,
                        "new_location": str(new_location_id)
                        if new_location_id is not None
                        else None,
                    },
                )
            )


__all__ = ["ResourceType", "Resource"]
