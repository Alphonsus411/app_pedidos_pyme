"""Entrega de una entrada outbox mediante puertos de almacenamiento y publicación."""

from dataclasses import dataclass
from typing import Protocol

from universal_business.application.events.publisher import EventPublisher
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import DomainEventId


@dataclass(frozen=True, kw_only=True)
class ClaimedOutboxEvent:
    """Evento y credencial opaca de una adjudicación temporal exclusiva."""

    event: DomainEvent
    claim_token: str

    def __post_init__(self) -> None:
        if not isinstance(self.event, DomainEvent):
            raise ValueError("Se requiere un evento de dominio")
        if not isinstance(self.claim_token, str) or not self.claim_token.strip():
            raise ValueError("Se requiere un token de adjudicación no vacío")


class OutboxDeliveryStore(Protocol):
    """Operaciones durables y atómicas del adaptador de entrega.

    claim_one confirma de forma durable una adjudicación temporal exclusiva
    antes de devolverla, o devuelve None. Sus tokens deben ser impredecibles
    y únicos por adjudicación, incluso después de que caduque. La duración y
    el reloj de la adjudicación pertenecen al adaptador.

    mark_delivered debe confirmar de forma atómica la entrega solo si el token
    aún corresponde a la adjudicación vigente y no caducada; ante pérdida de
    propiedad debe lanzar error y no cambiar el registro. Nunca debe eliminar
    ni marcar una entrada que pertenece a otra adjudicación.
    """

    def claim_one(self) -> ClaimedOutboxEvent | None:
        """Adjudica una entrada pendiente mediante transacción independiente."""
        raise NotImplementedError

    def mark_delivered(self, event_id: DomainEventId, claim_token: str, /) -> None:
        """Confirma la entrega exclusivamente bajo la adjudicación vigente."""
        raise NotImplementedError


class OutboxDeliveryWorker:
    """Procesa a lo sumo un evento por invocación; no programa reintentos.

    La publicación ocurre antes del marcado durable. Si se pierde la respuesta
    de publicación, falla el marcado o caduca la adjudicación, puede haber
    entregas duplicadas. Los consumidores deben deduplicar por event_id. Los
    fallos se propagan y el adaptador recupera la adjudicación tras su plazo.
    """

    def __init__(self, *, store: OutboxDeliveryStore, publisher: EventPublisher) -> None:
        self._store = store
        self._publisher = publisher

    def process_one(self) -> bool:
        """Devuelve False si no hay entrada; True solo tras publicar y marcar."""
        claim = self._store.claim_one()
        if claim is None:
            return False
        self._publisher.publish(claim.event)
        self._store.mark_delivered(claim.event.event_id, claim.claim_token)
        return True
