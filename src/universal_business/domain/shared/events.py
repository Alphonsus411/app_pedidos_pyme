"""DomainEvent base + AggregateRoot mixin para colección de eventos.

NO implementa dispatcher, outbox, bus, ni persistencia.
Sólo estructura + colección (para futuro patrón outbox).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar

from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import (
    BaseStrongId,
    DomainEventId,
)
from universal_business.domain.shared.value_objects.temporal import UTC, require_aware

if TYPE_CHECKING:  # pragma: no cover - evita import circular
    pass


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """Evento de dominio base mínimo (Corrección 13).

    Campos OBLIGATORIOS:
      - event_id:     id único del evento.
      - occurred_at:  datetime **aware** (UTC sugerido, cualquier zona OK).
      - aggregate_id: ID fuerte (UUID wrapper) del agregado que lo emitió.
      - aggregate_type: str, nombre del agregado (p. ej. "Customer", "Order").

    Campos OPCIONALES (cuando aplique):
      - tenant_id / business_id / location_id: contexto de aislamiento.
      - metadata: dict[str, Any] arbitrario serializable.
    """

    event_id: DomainEventId = field(default_factory=DomainEventId.generate)
    occurred_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(UTC))
    aggregate_id: BaseStrongId
    aggregate_type: str

    tenant_id: BaseStrongId | None = None
    business_id: BaseStrongId | None = None
    location_id: BaseStrongId | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_aware(self.occurred_at, field_name="DomainEvent.occurred_at")
        if not isinstance(self.aggregate_id, BaseStrongId):
            raise InvariantViolationError(
                f"DomainEvent.aggregate_id debe ser BaseStrongId: {self.aggregate_id!r}"
            )
        if not isinstance(self.event_id, DomainEventId):
            raise InvariantViolationError(
                f"DomainEvent.event_id debe ser DomainEventId: {self.event_id!r}"
            )
        if not isinstance(self.aggregate_type, str) or len(self.aggregate_type) < 3:
            raise InvariantViolationError(
                f"DomainEvent.aggregate_type inválido: {self.aggregate_type!r}"
            )
        if not isinstance(self.metadata, dict):
            raise InvariantViolationError(f"DomainEvent.metadata debe ser dict: {self.metadata!r}")

    @property
    def occurred_at_utc(self) -> dt.datetime:
        return self.occurred_at.astimezone(UTC)


T = TypeVar("T")


class AggregateRootMixin:
    """Mix-in opcional para agregados: colección de eventos de dominio.

    Diseñado para usarse junto a dataclasses: no define __init__ para no
    chocar con el __init__ generado por @dataclass. Los eventos se guardan
    en un atributo privado lazy.
    """

    def _get_event_store(self) -> list[DomainEvent]:
        store = self.__dict__.get("_stored_domain_events")
        if store is None:
            store = []
            self.__dict__["_stored_domain_events"] = store
        return store

    @property
    def domain_events(self) -> list[DomainEvent]:
        return list(self._get_event_store())

    def add_domain_event(self, event: DomainEvent) -> None:
        if not isinstance(event, DomainEvent):
            raise InvariantViolationError(f"No-DomainEvent pasado a add_domain_event: {event!r}")
        store = self._get_event_store()
        if any(e.event_id == event.event_id for e in store):
            return
        store.append(event)

    def clear_domain_events(self) -> None:
        self._get_event_store().clear()


__all__ = ["DomainEvent", "AggregateRootMixin"]
