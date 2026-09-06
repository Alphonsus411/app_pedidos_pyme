"""Módulo de dominio: Recursos reservables y su catálogo configurable."""

from __future__ import annotations

from universal_business.domain.resources.entities import (
    Resource,
)
from universal_business.domain.resources.entities import (
    ResourceType as ResourceTypeEntity,
)
from universal_business.domain.resources.events import (
    ResourceActivated,
    ResourceArchived,
    ResourceAssignedToLocation,
    ResourceCreated,
    ResourceDeactivated,
    ResourceTypeCreated,
)
from universal_business.domain.resources.ports import (
    IResourceRepository,
    IResourceTypeRepository,
)
from universal_business.domain.resources.value_objects import (
    ResourceStatus,
)
from universal_business.domain.resources.value_objects import (
    ResourceType as LegacyResourceTypeStrEnum,
)

ResourceType = LegacyResourceTypeStrEnum


__all__ = [
    "ResourceStatus",
    "ResourceType",
    "LegacyResourceTypeStrEnum",
    "ResourceTypeEntity",
    "Resource",
    "IResourceRepository",
    "IResourceTypeRepository",
    "ResourceTypeCreated",
    "ResourceCreated",
    "ResourceActivated",
    "ResourceDeactivated",
    "ResourceArchived",
    "ResourceAssignedToLocation",
]
