"""Capa de aplicación — Gate 0.2 Foundation.

Responsabilidades orquestacionales (nunca lógica de negocio):
- Commands / Queries / Handlers.
- UnitOfWork port (frontera transaccional lógica).
- Idempotency port.
- DomainEvent Dispatcher interno síncrono.
- EventPublisher port (integraciones externas futuras).
- Patrón de ejecución de casos de uso.
- Puerta para extensiones verticales (ADR-005).

**NO hay implementaciones concretas de infraestructura.**
Todos los ports son Protocol y se implementarán por adapters en Gate 0.5+.
"""

from __future__ import annotations

from universal_business.application.errors import (
    ApplicationError,
    HandlerNotFoundError,
    IdempotencyConflictError,
)
from universal_business.application.events import (
    DomainEventDispatcher,
    DomainEventHandler,
    EventPublisher,
)
from universal_business.application.execution import UseCaseHandler, execute_use_case
from universal_business.application.extensions import VerticalExtension, VerticalRegistry
from universal_business.application.idempotency import (
    IdempotencyKey,
    IdempotencyStore,
    InvalidIdempotencyKeyError,
)
from universal_business.application.messaging import (
    Command,
    CommandHandler,
    Query,
    QueryHandler,
)
from universal_business.application.unit_of_work import UnitOfWork

__all__ = [
    # Messaging
    "Command",
    "CommandHandler",
    "Query",
    "QueryHandler",
    # Errores
    "ApplicationError",
    "HandlerNotFoundError",
    "IdempotencyConflictError",
    # UoW
    "UnitOfWork",
    # Idempotencia
    "IdempotencyKey",
    "IdempotencyStore",
    "InvalidIdempotencyKeyError",
    # Events
    "DomainEventDispatcher",
    "DomainEventHandler",
    "EventPublisher",
    # Execution
    "UseCaseHandler",
    "execute_use_case",
    # Vertical extensions
    "VerticalExtension",
    "VerticalRegistry",
]
