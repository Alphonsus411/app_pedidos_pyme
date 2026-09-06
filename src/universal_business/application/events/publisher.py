"""EventPublisher — port externo de integración.

En Gate 0.2 **no hay implementación real**. Se define la interfaz Protocol que
los futuros backends (Outbox físico, Kafka, RabbitMQ, webhooks, SQS…) deben
implementar.

## Semántica fundamental

- :meth:`publish` / :meth:`publish_many` deben ser invocados **solo después**
  de :meth:`UnitOfWork.commit`. Jamás antes.
- Si el port requiere persistencia (Outbox) puede escribirse dentro del UoW;
  pero "publicar" (mover los mensajes al bus) es post-commit.
- **No** asumimos ordering, reintentos, persistencia, 2PC ni nada en esta
  interfaz. Esas propiedades son responsabilidad de cada adapter concreto.
- **No** mencionamos tecnologías concretas aquí.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from universal_business.domain.shared.events import DomainEvent


@runtime_checkable
class EventPublisher(Protocol):
    """Port de publicación externa de DomainEvent.

    Implementadores deben cumplir el contrato estructural:

    - :meth:`publish` envía un único evento.
    - :meth:`publish_many` envía 0..N eventos en el mismo lote (cuando el
      backend soporta batching, si no, equivalente a ``for e in evts: publish(e)``).
    """

    def publish(self, event: DomainEvent, /) -> None:
        """Publica un único DomainEvent hacia el backend externo."""
        raise NotImplementedError

    def publish_many(self, events: Iterable[DomainEvent], /) -> None:
        """Publica múltiples DomainEvent.

        La implementación por defecto (Protocol) simplemente delega a
        :meth:`publish` uno por uno. Los adapters pueden (y deben) sobrescribir
        esto con batching eficiente cuando el backend lo soporte.
        """
        for e in events:
            self.publish(e)


__all__ = ["EventPublisher"]
