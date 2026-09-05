"""Value objects del módulo business (enums de estado + VOs auxiliares).

Estados NO son compartidos: TenantStatus, BusinessStatus y LocationStatus
viven AQUÍ, NO en shared. (Corrección 2)
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, cast

from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.money import (
    CurrencyStr,
    _validate_currency,  # noqa: PLC2701 - module-level private helper
)
from universal_business.domain.shared.value_objects.temporal import TimeRange, require_aware

_ISO_ALPHA2_RE = re.compile(r"^[A-Z]{2}$")
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PHONE_MIN_LEN = 4

_WEEKDAY_NAMES: list[str] = [
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
    "SUNDAY",
]
Weekday = Literal["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
WEEKDAYS: tuple[Weekday, ...] = tuple(cast("list[Weekday]", _WEEKDAY_NAMES))


# ---------- Estados (no LifecycleStatus universal) ----------


class TenantStatus(StrEnum):
    PENDING_ONBOARDING = "pending_onboarding"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    BILLED_ONLY = "billed_only"
    TERMINATED = "terminated"


class BusinessStatus(StrEnum):
    DRAFT = "draft"
    OPERATIONAL = "operational"
    TEMPORARILY_CLOSED = "temporarily_closed"
    PERMANENTLY_CLOSED = "permanently_closed"


class LocationStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    TEMPORARILY_CLOSED = "temporarily_closed"
    CLOSED = "closed"


# ---------- VOs auxiliares ----------


@dataclass(frozen=True)
class Address:
    """Dirección física agnóstica de país. Nada de nombres específicos de sector."""

    country_code: str  # ISO-3166 alpha-2
    postal_code: str | None = None
    region: str | None = None
    city: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None

    def __post_init__(self) -> None:
        cc = self.country_code.strip().upper() if isinstance(self.country_code, str) else ""
        if not _ISO_ALPHA2_RE.fullmatch(cc):
            raise InvariantViolationError(
                f"Address.country_code inválido {self.country_code!r}. Esperado ISO-3166 alpha-2."
            )
        object.__setattr__(self, "country_code", cc)


@dataclass(frozen=True)
class ContactInfo:
    """Punto de contacto agregado: al menos uno debe estar presente."""

    email: str | None = None
    phone: str | None = None
    website: str | None = None

    def __post_init__(self) -> None:
        if not any([self.email, self.phone, self.website]):
            raise InvariantViolationError(
                "ContactInfo requiere al menos uno entre email, phone o website."
            )
        if self.email is not None and not _EMAIL_RE.fullmatch(self.email.strip()):
            raise InvariantViolationError(f"ContactInfo.email inválido: {self.email!r}")
        if self.phone is not None:
            digits = re.sub(r"\D", "", self.phone)
            if len(digits) < _PHONE_MIN_LEN:
                raise InvariantViolationError(
                    f"ContactInfo.phone inválido (min {_PHONE_MIN_LEN} dígitos): {self.phone!r}"
                )


@dataclass(frozen=True)
class BusinessSettings:
    """Configuración por empresa. NO flags verticales específicos."""

    default_currency: CurrencyStr
    feature_flags: dict[str, bool] = field(default_factory=dict)
    locale: str = "en-US"
    date_format: str = "YYYY-MM-DD"

    def __post_init__(self) -> None:
        cur = _validate_currency(self.default_currency)
        object.__setattr__(self, "default_currency", cur)
        if not isinstance(self.feature_flags, dict):
            raise InvariantViolationError("BusinessSettings.feature_flags debe ser dict[str, bool]")
        for k, v in self.feature_flags.items():
            if not isinstance(k, str) or not isinstance(v, bool):
                raise InvariantViolationError(
                    f"BusinessSettings.feature_flags[{k!r}]={v!r}: esperado str: bool"
                )


@dataclass(frozen=True)
class OperatingHours:
    """Horario semanal: 7 días, cada día = 0..N TimeRange (0 = cerrado)."""

    by_day: dict[Weekday, list[TimeRange]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized: dict[Weekday, list[TimeRange]] = {}
        for day_name in WEEKDAYS:
            ranges = self.by_day.get(day_name, [])
            if isinstance(ranges, TimeRange):
                ranges = [ranges]  # conveniencia
            clean: list[TimeRange] = []
            for r in ranges or []:
                if not isinstance(r, TimeRange):
                    raise InvariantViolationError(
                        f"OperatingHours[{day_name}]: entrada no es TimeRange: {r!r}"
                    )
                # TimeRange ya validó tz-aware y start<=end. Aquí NO ordenamos.
                clean.append(r)
            normalized[day_name] = clean
        object.__setattr__(self, "by_day", normalized)

    @property
    def weekdays(self) -> tuple[Weekday, ...]:
        return WEEKDAYS

    def open_slots(self, day: Weekday) -> list[TimeRange]:
        return list(self.by_day.get(day, []))

    def is_closed(self, day: Weekday) -> bool:
        return not self.by_day.get(day)

    def covers(self, moment: dt.datetime) -> bool:
        require_aware(moment, field_name="OperatingHours.covers(moment)")
        # Determinar día según el datetime EN SU ZONA (la zona de la Location es
        # responsabilidad de quién instancia el OperatingHours; aquí aceptamos
        # cualquier zona y miramos weekday en su tz local).
        idx = moment.weekday()  # Monday=0
        day_name: Weekday = WEEKDAYS[idx]
        for slot in self.by_day.get(day_name, []):
            if moment in slot:
                return True
        return False


__all__ = [
    "TenantStatus",
    "BusinessStatus",
    "LocationStatus",
    "Weekday",
    "WEEKDAYS",
    "Address",
    "ContactInfo",
    "BusinessSettings",
    "OperatingHours",
]
