"""Entidades de negocio del módulo business: Tenant / Business / Location.

Jerarquía:
  Tenant (límite SaaS, no necesariamente entidad legal)
    └─ Business (unidad operativa)
         └─ Location (establecimiento físico o lógico)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from universal_business.domain.business.value_objects import (
    Address,
    BusinessSettings,
    BusinessStatus,
    ContactInfo,
    LocationStatus,
    OperatingHours,
    TenantStatus,
)
from universal_business.domain.shared.base import BaseEntity
from universal_business.domain.shared.errors import (
    InvariantViolationError,
    TenantBoundaryViolationError,
)
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    TenantId,
)
from universal_business.domain.shared.value_objects.status import StatusTransition

if TYPE_CHECKING:  # pragma: no cover
    pass

_NAME_MIN = 2
_NAME_MAX = 100

_TRANSITIONS_TENANT: dict[TenantStatus, set[TenantStatus]] = {
    TenantStatus.PENDING_ONBOARDING: {TenantStatus.ACTIVE, TenantStatus.TERMINATED},
    TenantStatus.ACTIVE: {
        TenantStatus.SUSPENDED,
        TenantStatus.BILLED_ONLY,
        TenantStatus.TERMINATED,
    },
    TenantStatus.SUSPENDED: {TenantStatus.ACTIVE, TenantStatus.TERMINATED},
    TenantStatus.BILLED_ONLY: {TenantStatus.ACTIVE, TenantStatus.TERMINATED},
    TenantStatus.TERMINATED: set(),
}
_TRANSITIONS_BUSINESS: dict[BusinessStatus, set[BusinessStatus]] = {
    BusinessStatus.DRAFT: {BusinessStatus.OPERATIONAL, BusinessStatus.PERMANENTLY_CLOSED},
    BusinessStatus.OPERATIONAL: {
        BusinessStatus.TEMPORARILY_CLOSED,
        BusinessStatus.PERMANENTLY_CLOSED,
    },
    BusinessStatus.TEMPORARILY_CLOSED: {
        BusinessStatus.OPERATIONAL,
        BusinessStatus.PERMANENTLY_CLOSED,
    },
    BusinessStatus.PERMANENTLY_CLOSED: set(),
}
_TRANSITIONS_LOCATION: dict[LocationStatus, set[LocationStatus]] = {
    LocationStatus.DRAFT: {LocationStatus.OPEN, LocationStatus.CLOSED},
    LocationStatus.OPEN: {LocationStatus.TEMPORARILY_CLOSED, LocationStatus.CLOSED},
    LocationStatus.TEMPORARILY_CLOSED: {LocationStatus.OPEN, LocationStatus.CLOSED},
    LocationStatus.CLOSED: set(),
}

_TENANT_FSM = StatusTransition(_TRANSITIONS_TENANT)
_BUSINESS_FSM = StatusTransition(_TRANSITIONS_BUSINESS)
_LOCATION_FSM = StatusTransition(_TRANSITIONS_LOCATION)


def _validate_display_name(name: str, field: str) -> None:
    if not isinstance(name, str):
        raise InvariantViolationError(f"{field}: debe ser str, recibido {type(name).__name__}")
    n = name.strip()
    if not (_NAME_MIN <= len(n) <= _NAME_MAX):
        raise InvariantViolationError(
            f"{field}: longitud {len(n)!r} fuera del rango [{_NAME_MIN}, {_NAME_MAX}]: {name!r}"
        )


# =============================================================================
# Tenant
# =============================================================================


@dataclass(kw_only=True)
class Tenant(BaseEntity[TenantId]):
    """Límite superior de aislamiento SaaS (Corrección 4).

    Tenant NO es sinónimo de persona jurídica. Una cuenta SaaS individual, un
    grupo empresarial o una franquicia completa pueden ser un solo Tenant.
    """

    display_name: str
    status: TenantStatus = TenantStatus.PENDING_ONBOARDING
    legal_entity_name: str | None = None
    legal_tax_id: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_display_name(self.display_name, "Tenant.display_name")
        object.__setattr__(self, "display_name", self.display_name.strip())
        # Si hay legal_tax_id, debe haber legal_entity_name
        if self.legal_tax_id is not None and not self.legal_entity_name:
            raise InvariantViolationError(
                "Tenant.legal_tax_id requiere legal_entity_name definido."
            )

    def transition_to(self, next_status: TenantStatus) -> None:
        _TENANT_FSM.ensure(self.status, next_status)
        object.__setattr__(self, "status", next_status)
        self.touch()

    @property
    def is_legal_entity(self) -> bool:
        return bool(self.legal_entity_name)


# =============================================================================
# Business
# =============================================================================


@dataclass(kw_only=True)
class Business(BaseEntity[BusinessId]):
    """Unidad operativa dentro de un Tenant."""

    tenant_id: TenantId
    name: str
    contact_info: ContactInfo
    settings: BusinessSettings
    status: BusinessStatus = BusinessStatus.DRAFT
    description: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_display_name(self.name, "Business.name")
        object.__setattr__(self, "name", self.name.strip())
        if self.description is not None and len(self.description) > 1000:
            raise InvariantViolationError(
                f"Business.description: max 1000 chars ({len(self.description)})"
            )
        if not isinstance(self.contact_info, ContactInfo):
            raise InvariantViolationError("Business.contact_info debe ser ContactInfo VO")
        if not isinstance(self.settings, BusinessSettings):
            raise InvariantViolationError("Business.settings debe ser BusinessSettings VO")

    def transition_to(self, next_status: BusinessStatus) -> None:
        _BUSINESS_FSM.ensure(self.status, next_status)
        object.__setattr__(self, "status", next_status)
        self.touch()

    def owns(self, location: Location) -> bool:
        return location.business_id == self.id and location.tenant_id == self.tenant_id


# =============================================================================
# Location
# =============================================================================


@dataclass(kw_only=True)
class Location(BaseEntity[LocationId]):
    """Establecimiento físico / lógico bajo un Business."""

    tenant_id: TenantId
    business_id: BusinessId
    name: str
    address: Address
    timezone: str
    operating_hours: OperatingHours
    status: LocationStatus = LocationStatus.DRAFT
    contact_info: ContactInfo | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_display_name(self.name, "Location.name")
        object.__setattr__(self, "name", self.name.strip())
        if not isinstance(self.address, Address):
            raise InvariantViolationError("Location.address debe ser Address VO")
        if not isinstance(self.timezone, str) or (
            "/" not in self.timezone and self.timezone != "UTC"
        ):
            # Validación ligera: IANA p. ej. "America/Santo_Domingo" o "UTC".
            # No usamos zoneinfo para no depender de DBs; comprobación razonable.
            raise InvariantViolationError(
                f"Location.timezone no parece IANA válido: {self.timezone!r}"
            )
        if not isinstance(self.operating_hours, OperatingHours):
            raise InvariantViolationError("Location.operating_hours debe ser OperatingHours VO")
        # Invariante de tenancy: location.tenant_id == business.tenant_id conceptualmente
        # (no tenemos el Business para validar el FK real, pero sí rechazamos si
        # nos pasan un `location.tenant_id` distinto de `id.tenant_id` cuando se
        # suministra a través de factories). Aceptamos que la comprobación se
        # realiza en aplicación, pero registramos el requisito aquí mediante un
        # comentario y una comprobación que garantice consistencia dentro del
        # aggregate: el propio Location no puede tener otro tenant_id que su
        # propiedad interna, claro que sí coincide — garantizamos `not None`.
        if self.tenant_id is None or self.business_id is None:  # pragma: no cover
            raise TenantBoundaryViolationError("Location.tenant_id y business_id son obligatorios.")

    def transition_to(self, next_status: LocationStatus) -> None:
        _LOCATION_FSM.ensure(self.status, next_status)
        object.__setattr__(self, "status", next_status)
        self.touch()

    def assert_tenancy_consistency(self, business: Business) -> None:
        """Invocado desde repositorios/casos de uso antes de persistir."""
        if business.id != self.business_id:
            raise InvariantViolationError(
                f"Location.business_id={self.business_id!s} no coincide con Business.id={business.id!s}"
            )
        if business.tenant_id != self.tenant_id:
            raise TenantBoundaryViolationError(
                "Location.tenant_id difiere de Business.tenant_id (violación de aislamiento)."
            )


__all__ = ["Tenant", "Business", "Location"]
