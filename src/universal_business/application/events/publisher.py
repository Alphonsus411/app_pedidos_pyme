"""EventPublisher — port externo de integración (**exclusivamente post-commit**).

En Gate 0.2 **no hay implementación real**. Se define la interfaz Protocol que
los futuros backends (Outbox físico *consumer*, Kafka, RabbitMQ, webhooks, SQS…)
deben implementar.

## Semántica fundamental

- :meth:`publish` / :meth:`publish_many` deben ser invocados **solo después**
  de :meth:`UnitOfWork.commit`. Jamás antes.
- **Este port NO garantiza atomicidad DB + mensaje.** Ser llamado post-commit
  significa que los datos ya están persistidos; si el publisher falla el dominio
  no se deshace. Futuros mecanismos de entrega garantizada (reintentos, DLQ,
  Outbox real) son responsabilidad del adapter de infraestructura.
- **Este port NO escribe una tabla Outbox dentro del UnitOfWork.** Si en Gate
  0.5+ se adopta el patrón Transactional Outbox, existirá un contrato
  **separado** (p. ej. ``TransactionalOutboxWriter``) que se invocará
  **pre-commit** dentro del UoW; :class:`EventPublisher` seguirá siendo el
  componente post-commit que lee/mueve mensajes hacia el bus externo. Los dos
  conceptos no comparten interfaz.
- **No** asumimos ordering, deduplicación, persistencia, 2PC ni nada en esta
  interfaz. Esas propiedades son responsabilidad de cada adapter concreto.
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
