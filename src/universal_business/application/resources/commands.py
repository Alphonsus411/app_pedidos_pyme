"""Commands concretos para el módulo Resources (Gate 0.3).

Todos los commands heredan de :class:`Command` (frozen, kw_only=True) y
llevan ``tenant_id`` + ``business_id`` explícitos (regla de tenancy Gate 0.1).
Los commands de creación llevan ``idempotency_key`` opcional.
"""

from __future__ import annotations

from dataclasses import dataclass

from universal_business.application.idempotency import IdempotencyKey
from universal_business.application.messaging.commands import Command
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    ResourceId,
    ResourceTypeId,
    TenantId,
)


@dataclass(frozen=True, kw_only=True)
class CreateResourceType(Command):
    tenant_id: TenantId
    business_id: BusinessId
    resource_type_id: ResourceTypeId
    name: str
    description: str | None = None
    idempotency_key: IdempotencyKey | None = None


@dataclass(frozen=True, kw_only=True)
class CreateResource(Command):
    tenant_id: TenantId
    business_id: BusinessId
    resource_id: ResourceId
    resource_type_id: ResourceTypeId
    name: str
    location_id: LocationId | None = None
    capacity: int = 0
    idempotency_key: IdempotencyKey | None = None


@dataclass(frozen=True, kw_only=True)
class ActivateResource(Command):
    tenant_id: TenantId
    business_id: BusinessId
    resource_id: ResourceId


@dataclass(frozen=True, kw_only=True)
class DeactivateResource(Command):
    tenant_id: TenantId
    business_id: BusinessId
    resource_id: ResourceId


@dataclass(frozen=True, kw_only=True)
class ArchiveResource(Command):
    tenant_id: TenantId
    business_id: BusinessId
    resource_id: ResourceId


@dataclass(frozen=True, kw_only=True)
class AssignResourceToLocation(Command):
    tenant_id: TenantId
    business_id: BusinessId
    resource_id: ResourceId
    new_location_id: LocationId | None = None


__all__ = [
    "CreateResourceType",
    "CreateResource",
    "ActivateResource",
    "DeactivateResource",
    "ArchiveResource",
    "AssignResourceToLocation",
]
