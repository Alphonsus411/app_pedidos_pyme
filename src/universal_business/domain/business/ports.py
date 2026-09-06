"""Puertos / contratos de repositorio para el módulo business (Hardening Gate 0.1-RC1).

Cerca del dominio propietario. typing.Protocol.

Tenant: límite superior de aislamiento SaaS. Todas las operaciones tenant-scoped
requieren tenant_id explícito para acceso/filtrado.
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
    """Acceso agregado a Tenant.

    Tenant ES el límite superior; su propia identidad ya define el boundary.
    Operaciones de recuperación por lista requieren tenant_id en save/delete deben validar
    contra la propia entidad.
    """

    def get(self, tenant_id: TenantId) -> Tenant | None: ...
    def save(self, tenant: Tenant) -> None: ...
    def list(self, *, status: TenantStatus | None = None) -> list[Tenant]: ...


class IBusinessRepository(Protocol):
    """Business pertenece a un Tenant. get requiere tenant_id explícito."""

    def get(
        self,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
    ) -> Business | None: ...
    def save(self, business: Business) -> None: ...
    def list_by_tenant(
        self, tenant_id: TenantId, *, status: BusinessStatus | None = None
    ) -> list[Business]: ...


class ILocationRepository(Protocol):
    """Location pertenece a Business → Tenant.

    - get: requiere tenant_id + business_id + location_id (3 niveles para
      garantizan consistencia.
    - list_by_business: añade tenant_id explícito para no listar locations de
      otros tenants bajo el mismo business_id (id único a nivel global pero
      mejor ser redundante por seguridad.
    """

    def get(
        self,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId,
    ) -> Location | None: ...
    def save(self, location: Location) -> None: ...
    def list_by_business(
        self,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        status: LocationStatus | None = None,
    ) -> list[Location]: ...


__all__ = ["ITenantRepository", "IBusinessRepository", "ILocationRepository"]
