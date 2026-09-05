"""Entidades base de utilidad real. No jerarquías profundas.

BaseEntity aporta:
  - identidad (id fuertemente tipada)
  - timestamps timezone-aware
  - soporte para colección de eventos (AggregateRootMixin)

AggregateRoot = BaseEntity + AggregateRootMixin.
"""

from __future__ import annotations

import abc
import datetime as dt
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.events import AggregateRootMixin, DomainEvent
from universal_business.domain.shared.value_objects.ids import BaseStrongId
from universal_business.domain.shared.value_objects.temporal import UTC, require_aware

IdT = TypeVar("IdT", bound=BaseStrongId)


@dataclass(kw_only=True)
class BaseEntity(abc.ABC, AggregateRootMixin, Generic[IdT]):
    """Base concreta para entidades con identidad persistente.

    Uso:
        @dataclass(kw_only=True)
        class Tenant(BaseEntity[TenantId]):
            ...
    """

    id: IdT
    created_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(UTC))
    updated_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(UTC))

    def __post_init__(self) -> None:
        if not isinstance(self.id, BaseStrongId):
            raise InvariantViolationError(
                f"{type(self).__name__}.id debe ser un BaseStrongId: {self.id!r}"
            )
        require_aware(self.created_at, field_name=f"{type(self).__name__}.created_at")
        require_aware(self.updated_at, field_name=f"{type(self).__name__}.updated_at")
        if self.updated_at < self.created_at:
            raise InvariantViolationError(
                f"{type(self).__name__}.updated_at < created_at: "
                f"{self.updated_at.isoformat()} < {self.created_at.isoformat()}"
            )

    def touch(self, when: dt.datetime | None = None) -> None:
        """Actualiza updated_at. Debe usarse en cada mutación."""
        ts = when if when is not None else dt.datetime.now(UTC)
        require_aware(ts, field_name=f"{type(self).__name__}.touch.ts")
        object.__setattr__(self, "updated_at", ts)

    def add_domain_event(self, event: DomainEvent) -> None:  # noqa: D401 - redocumentar
        """Override mínimo para asegurar aggregate_id == self.id cuando no se pasó."""
        if not isinstance(event, DomainEvent):
            raise InvariantViolationError(f"Evento inválido pasado a add_domain_event: {event!r}")
        super().add_domain_event(event)


__all__ = ["BaseEntity", "IdT"]
