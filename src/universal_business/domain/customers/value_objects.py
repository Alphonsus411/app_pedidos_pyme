"""Value objects propios del módulo customers.

CustomerStatus vive AQUÍ, NO en shared. (Corrección 2)
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.temporal import require_aware


class CustomerStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ANONYMIZED = "anonymized"
    ARCHIVED = "archived"


ContactKind = Literal["EMAIL", "PHONE", "WHATSAPP", "INSTAGRAM", "OTHER"]
VALID_CONTACT_KINDS: set[str] = {"EMAIL", "PHONE", "WHATSAPP", "INSTAGRAM", "OTHER"}

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


@dataclass(frozen=True)
class ContactPoint:
    """Punto de contacto individual para un Customer (email, teléfono, etc.)."""

    kind: ContactKind
    value: str
    is_primary: bool = False
    verified_at: dt.datetime | None = None

    def __post_init__(self) -> None:
        if self.kind not in VALID_CONTACT_KINDS:
            raise InvariantViolationError(f"ContactPoint.kind inválido: {self.kind!r}")
        if not isinstance(self.value, str) or not self.value.strip():
            raise InvariantViolationError("ContactPoint.value no puede ser vacío")
        object.__setattr__(self, "value", self.value.strip())
        if self.kind == "EMAIL" and not _EMAIL_RE.fullmatch(self.value):
            raise InvariantViolationError(f"ContactPoint EMAIL inválido: {self.value!r}")
        if self.kind == "PHONE":
            digits = re.sub(r"\D", "", self.value)
            if len(digits) < 4:
                raise InvariantViolationError(f"ContactPoint PHONE inválido: {self.value!r}")
        if self.verified_at is not None:
            require_aware(self.verified_at, field_name="ContactPoint.verified_at")


ConsentKind = Literal["TERMS_AND_CONDITIONS", "PRIVACY_POLICY", "MARKETING", "COMMUNICATIONS"]
VALID_CONSENT_KINDS: set[str] = {
    "TERMS_AND_CONDITIONS",
    "PRIVACY_POLICY",
    "MARKETING",
    "COMMUNICATIONS",
}


@dataclass(frozen=True)
class Consent:
    """Registro de consentimiento otorgado o revocado por un Customer."""

    kind: ConsentKind
    source: str
    granted_at: dt.datetime
    revoked_at: dt.datetime | None = None

    def __post_init__(self) -> None:
        if self.kind not in VALID_CONSENT_KINDS:
            raise InvariantViolationError(f"Consent.kind inválido: {self.kind!r}")
        if not isinstance(self.source, str) or not self.source.strip():
            raise InvariantViolationError("Consent.source debe ser str no vacío")
        require_aware(self.granted_at, field_name="Consent.granted_at")
        if self.revoked_at is not None:
            require_aware(self.revoked_at, field_name="Consent.revoked_at")
            if self.revoked_at < self.granted_at:
                raise InvariantViolationError("Consent.revoked_at < granted_at")

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


@dataclass(frozen=True)
class CustomerPreferences:
    """Preferencias operacionales de un Customer. Nada sectorial."""

    language_tag: str = "en-US"
    opt_in_sms: bool = False
    opt_in_email: bool = False
    opt_in_whatsapp: bool = False
    notes: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.language_tag, str) or len(self.language_tag) < 2:
            raise InvariantViolationError(
                f"CustomerPreferences.language_tag inválido: {self.language_tag!r}"
            )


__all__ = [
    "CustomerStatus",
    "ContactPoint",
    "Consent",
    "CustomerPreferences",
    "ContactKind",
    "ConsentKind",
]
