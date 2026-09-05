"""Aggregado mínimo Resource (reservable atómico)."""

from __future__ import annotations

from dataclasses import dataclass

from universal_business.domain.resources.value_objects import ResourceStatus, ResourceType
from universal_business.domain.shared.base import BaseEntity
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    ResourceId,
    TenantId,
)


@dataclass(kw_only=True)
class Resource(BaseEntity[ResourceId]):
    """Recurso reservable atómico. Pertenencia FÍSICA a una Location."""

    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId  # OBLIGATORIO: Resource pertenece físicamente a una Location
    name: str
    type: ResourceType
    status: ResourceStatus = ResourceStatus.ACTIVE
    capacity: int | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.name, str) or not self.name.strip():
            raise InvariantViolationError("Resource.name no puede ser vacío")
        object.__setattr__(self, "name", self.name.strip())
        if not isinstance(self.type, ResourceType):
            raise InvariantViolationError("Resource.type debe ser ResourceType")
        if not isinstance(self.status, ResourceStatus):
            raise InvariantViolationError("Resource.status debe ser ResourceStatus")
        if self.capacity is not None and self.capacity < 0:
            raise InvariantViolationError("Resource.capacity no puede ser negativo")


__all__ = ["Resource"]
