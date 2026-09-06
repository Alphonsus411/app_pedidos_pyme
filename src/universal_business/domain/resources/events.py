"""Eventos de dominio para módulo Resources."""

from __future__ import annotations

from dataclasses import dataclass

from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import (
    BaseStrongId,
    LocationId,
    ResourceTypeId,
)


@dataclass(frozen=True, kw_only=True)
class ResourceTypeCreated(DomainEvent):
    aggregate_type: str = "ResourceType"


@dataclass(frozen=True, kw_only=True)
class ResourceCreated(DomainEvent):
    aggregate_type: str = "Resource"
    resource_type_id: ResourceTypeId
    location_id: LocationId | None = None


@dataclass(frozen=True, kw_only=True)
class ResourceActivated(DomainEvent):
    aggregate_type: str = "Resource"


@dataclass(frozen=True, kw_only=True)
class ResourceDeactivated(DomainEvent):
    aggregate_type: str = "Resource"


@dataclass(frozen=True, kw_only=True)
class ResourceArchived(DomainEvent):
    aggregate_type: str = "Resource"


@dataclass(frozen=True, kw_only=True)
class ResourceAssignedToLocation(DomainEvent):
    aggregate_type: str = "Resource"
    old_location_id: BaseStrongId | None = None
    new_location_id: BaseStrongId | None = None


__all__ = [
    "ResourceTypeCreated",
    "ResourceCreated",
    "ResourceActivated",
    "ResourceDeactivated",
    "ResourceArchived",
    "ResourceAssignedToLocation",
]
