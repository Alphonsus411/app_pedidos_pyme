"""Primitivas de eventos en capa aplicación. Gate 0.2 Foundation.

- :mod:`~universal_business.application.events.dispatcher` — handlers síncronos
  internos y dispatcher lógico.
- :mod:`~universal_business.application.events.publisher` — port Protocol para
  publicar DomainEvent hacia sistemas externos (Outbox, Kafka, RabbitMQ,
  webhooks...). Implementación concreta: Gate 0.5+.
"""

from __future__ import annotations

from universal_business.application.events.dispatcher import (
    DomainEventDispatcher,
    DomainEventHandler,
)
from universal_business.application.events.publisher import EventPublisher

__all__ = [
    "DomainEventDispatcher",
    "DomainEventHandler",
    "EventPublisher",
]
