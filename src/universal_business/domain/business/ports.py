"""Puertos / contratos de repositorio para el módulo business (Corrección 7).

Cerca del dominio propietario, punto central agregador. typing.Protocol.
"""

from __future__ import annotations

from typing import Protocol

from universal_business.domain.business.entities import Business, Location, Tenant
from universal_business.domain.business.value_objects import (
    BusinessStatus,
    LocationStatus,
    TenantStatus,
)
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    TenantId,
)


class ITenantRepository(Protocol):
    """Acceso agregado a Tenant. Todas las operaciones retornan entidades de dominio."""

    def get(self, tenant_id: TenantId) -> Tenant | None: ...
    def save(self, tenant: Tenant) -> None: ...
    def list(self, *, status: TenantStatus | None = None) -> list[Tenant]: ...


class IBusinessRepository(Protocol):
    def get(self, business_id: BusinessId) -> Business | None: ...
    def save(self, business: Business) -> None: ...
    def list_by_tenant(
        self, tenant_id: TenantId, *, status: BusinessStatus | None = None
    ) -> list[Business]: ...


class ILocationRepository(Protocol):
    def get(self, location_id: LocationId) -> Location | None: ...
    def save(self, location: Location) -> None: ...
    def list_by_business(
        self, business_id: BusinessId, *, status: LocationStatus | None = None
    ) -> list[Location]: ...


__all__ = ["ITenantRepository", "IBusinessRepository", "ILocationRepository"]
