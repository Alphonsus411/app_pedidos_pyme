"""Aggregado Customer.

Corrección 3: Customer NO debe quedar permanentemente ligado a una Location.
- tenant_id    : OBLIGATORIO
- business_id  : OBLIGATORIO (decisión del plan v2 — default actual)
- location_id  : OPCIONAL, NO parte de la identidad. Puede ser None (el
                 customer pertenece al business entero y opera en varias
                 Locations a través de Orders / Reservations).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from universal_business.domain.business.value_objects import Address as CustomerAddress
from universal_business.domain.customers.value_objects import (
    Consent,
    ContactPoint,
    CustomerPreferences,
    CustomerStatus,
)
from universal_business.domain.shared.base import BaseEntity
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CustomerId,
    LocationId,
    TenantId,
)
from universal_business.domain.shared.value_objects.status import StatusTransition

if TYPE_CHECKING:  # pragma: no cover
    pass


_GIVEN_NAME_MIN = 1
_GIVEN_NAME_MAX = 100

CUSTOMER_TRANSITIONS: dict[CustomerStatus, set[CustomerStatus]] = {
    CustomerStatus.DRAFT: {CustomerStatus.ACTIVE, CustomerStatus.ARCHIVED},
    CustomerStatus.ACTIVE: {
        CustomerStatus.SUSPENDED,
        CustomerStatus.ANONYMIZED,
        CustomerStatus.ARCHIVED,
    },
    CustomerStatus.SUSPENDED: {
        CustomerStatus.ACTIVE,
        CustomerStatus.ANONYMIZED,
        CustomerStatus.ARCHIVED,
    },
    CustomerStatus.ANONYMIZED: {CustomerStatus.ARCHIVED},
    CustomerStatus.ARCHIVED: set(),
}
_CUSTOMER_FSM = StatusTransition(CUSTOMER_TRANSITIONS)


@dataclass(kw_only=True)
class Customer(BaseEntity[CustomerId]):
    """Agregado Customer: persona / empresa que interactúa con el Business."""

    tenant_id: TenantId
    business_id: BusinessId
    given_name: str
    contact_points: list[ContactPoint] = field(default_factory=list)
    addresses: list[CustomerAddress] = field(default_factory=list)
    consents: list[Consent] = field(default_factory=list)
    preferences: CustomerPreferences = field(default_factory=CustomerPreferences)
    status: CustomerStatus = CustomerStatus.DRAFT
    location_id: LocationId | None = None  # NO parte de la identidad
    external_ref: str | None = None
    family_name: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        # Nombre
        if not isinstance(self.given_name, str):
            raise InvariantViolationError("Customer.given_name debe ser str")
        gn = self.given_name.strip()
        if not (_GIVEN_NAME_MIN <= len(gn) <= _GIVEN_NAME_MAX):
            raise InvariantViolationError(
                f"Customer.given_name longitud inválida {len(gn)!r}: {self.given_name!r}"
            )
        object.__setattr__(self, "given_name", gn)
        if self.family_name is not None:
            fn = self.family_name.strip()
            if len(fn) > _GIVEN_NAME_MAX:
                raise InvariantViolationError(
                    f"Customer.family_name demasiado largo ({len(fn)}): {self.family_name!r}"
                )
            object.__setattr__(self, "family_name", fn or None)
        # contact_points
        for i, cp in enumerate(self.contact_points):
            if not isinstance(cp, ContactPoint):
                raise InvariantViolationError(
                    f"Customer.contact_points[{i}] no es ContactPoint: {cp!r}"
                )
        if self.status == CustomerStatus.ACTIVE and not self.contact_points:
            raise InvariantViolationError("Customer ACTIVE requiere al menos 1 ContactPoint.")
        # addresses
        for i, a in enumerate(self.addresses):
            if not isinstance(a, CustomerAddress):
                raise InvariantViolationError(f"Customer.addresses[{i}] no es Address: {a!r}")
        # consents
        for i, c in enumerate(self.consents):
            if not isinstance(c, Consent):
                raise InvariantViolationError(f"Customer.consents[{i}] no es Consent: {c!r}")
        # preferences
        if not isinstance(self.preferences, CustomerPreferences):
            raise InvariantViolationError("Customer.preferences debe ser CustomerPreferences")
        # external_ref uniqueness se valida a nivel repositorio; aquí el invariante
        # estructural: si existe, no puede ser str vacía tras strip.
        if self.external_ref is not None:
            er = self.external_ref.strip()
            if not er:
                raise InvariantViolationError("Customer.external_ref: str vacía no permitida")
            object.__setattr__(self, "external_ref", er)

    @property
    def full_name(self) -> str:
        parts = [self.given_name, self.family_name]
        return " ".join(p for p in parts if p)

    def transition_to(self, next_status: CustomerStatus) -> None:
        _CUSTOMER_FSM.ensure(self.status, next_status)
        if next_status == CustomerStatus.ACTIVE and not self.contact_points:
            raise InvariantViolationError("Customer ACTIVE requiere al menos 1 ContactPoint.")
        object.__setattr__(self, "status", next_status)
        self.touch()

    def add_contact_point(self, cp: ContactPoint) -> None:
        if not isinstance(cp, ContactPoint):
            raise InvariantViolationError(f"add_contact_point: no es ContactPoint: {cp!r}")
        # Si se marca como primario, quitar la bandera del anterior
        if cp.is_primary:
            existing = list(self.contact_points)
            for i, old in enumerate(existing):
                if old.is_primary and (old.kind, old.value) != (cp.kind, cp.value):
                    # Copiar el objeto frozen sin la bandera
                    from dataclasses import replace

                    existing[i] = replace(old, is_primary=False)
            existing.append(cp)
            object.__setattr__(self, "contact_points", existing)
        else:
            self.contact_points.append(cp)
        self.touch()

    @property
    def primary_contact(self) -> ContactPoint | None:
        for cp in self.contact_points:
            if cp.is_primary:
                return cp
        return self.contact_points[0] if self.contact_points else None

    def add_address(self, addr: CustomerAddress) -> None:
        if not isinstance(addr, CustomerAddress):
            raise InvariantViolationError(f"add_address: no es Address: {addr!r}")
        self.addresses.append(addr)
        self.touch()

    def record_consent(self, consent: Consent) -> None:
        if not isinstance(consent, Consent):
            raise InvariantViolationError(f"record_consent: no es Consent: {consent!r}")
        self.consents.append(consent)
        self.touch()


__all__ = ["Customer"]
