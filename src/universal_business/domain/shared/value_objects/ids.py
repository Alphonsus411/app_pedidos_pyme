"""IDs fuertes tipados para todos los agregados de dominio.

Wrapper dataclass inmutable sobre UUID. No depende de persistencia.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TypeVar
from uuid import UUID, uuid4

from universal_business.domain.shared.errors import InvariantViolationError

_UUID_STR_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

T = TypeVar("T", bound="BaseStrongId")


def _parse_uuid(value: UUID | str | int | bytes) -> UUID:
    """Coerción segura a UUID. Acepta UUID, str, int, bytes; rechaza lo demás."""
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        if not _UUID_STR_RE.fullmatch(value.strip()):
            raise InvariantViolationError(f"ID no es un UUID válido: {value!r}")
        return UUID(value.strip())
    if isinstance(value, (int, bytes)):
        try:
            return UUID(int=value) if isinstance(value, int) else UUID(bytes=value)
        except Exception as exc:  # noqa: BLE001 - conversión genérica
            raise InvariantViolationError(f"ID formato inválido: {value!r}") from exc
    raise InvariantViolationError(
        f"ID tipo no soportado: {type(value).__name__}. Usa UUID, str, int o bytes."
    )


@dataclass(frozen=True, repr=False)
class BaseStrongId:
    """Clase base (composición, no herencia profunda) para IDs fuertes.

    Todos heredan de ésta. El comportamiento es idéntico; lo que cambia es el
    nombre del tipo para seguridad estática (mypy) y semántica en runtime.
    """

    raw: UUID = field(default_factory=uuid4, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.raw, UUID):
            # Permitir que se pase str/int/bytes por accidente y coercerlo
            object.__setattr__(self, "raw", _parse_uuid(self.raw))

    @classmethod
    def generate(cls: type[T]) -> T:
        return cls()

    @classmethod
    def from_raw(cls: type[T], value: UUID | str | int | bytes) -> T:
        return cls(raw=_parse_uuid(value))

    def __str__(self) -> str:
        return str(self.raw)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.raw!s})"

    @property
    def hex(self) -> str:
        return self.raw.hex

    def to_dict(self) -> dict[str, str]:
        return {"value": str(self.raw)}


# ---- IDs concretos por agregado ----


@dataclass(frozen=True, repr=False)
class TenantId(BaseStrongId):
    pass


@dataclass(frozen=True, repr=False)
class BusinessId(BaseStrongId):
    pass


@dataclass(frozen=True, repr=False)
class LocationId(BaseStrongId):
    pass


@dataclass(frozen=True, repr=False)
class CustomerId(BaseStrongId):
    pass


@dataclass(frozen=True, repr=False)
class CatalogItemId(BaseStrongId):
    pass


@dataclass(frozen=True, repr=False)
class ResourceId(BaseStrongId):
    pass


@dataclass(frozen=True, repr=False)
class ReservationId(BaseStrongId):
    pass


@dataclass(frozen=True, repr=False)
class OrderId(BaseStrongId):
    pass


@dataclass(frozen=True, repr=False)
class FulfillmentId(BaseStrongId):
    pass


@dataclass(frozen=True, repr=False)
class AvailabilityRuleId(BaseStrongId):
    pass


@dataclass(frozen=True, repr=False)
class AvailabilityBlockId(BaseStrongId):
    pass


@dataclass(frozen=True, repr=False)
class DomainEventId(BaseStrongId):
    pass


@dataclass(frozen=True, repr=False)
class OfferingId(BaseStrongId):
    pass


@dataclass(frozen=True, repr=False)
class CatalogCategoryId(BaseStrongId):
    pass


@dataclass(frozen=True, repr=False)
class ResourceTypeId(BaseStrongId):
    pass


# Permite dict-lookup por valor (UUID) sin depender de nombres específicos.
def _as_id_pair(val: BaseStrongId) -> tuple[str, str]:
    return (type(val).__name__, str(val))


AnyStrongId = BaseStrongId  # alias legible

__all__ = [
    "BaseStrongId",
    "TenantId",
    "BusinessId",
    "LocationId",
    "CustomerId",
    "CatalogItemId",
    "OfferingId",
    "CatalogCategoryId",
    "ResourceTypeId",
    "ResourceId",
    "ReservationId",
    "OrderId",
    "FulfillmentId",
    "AvailabilityRuleId",
    "AvailabilityBlockId",
    "DomainEventId",
    "AnyStrongId",
]
