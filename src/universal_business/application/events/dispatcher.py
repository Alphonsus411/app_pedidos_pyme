"""Domain Event Handler (interno síncrono) + Domain Event Dispatcher lógico.

## Distinción clave (dispatcher vs publisher — NO confundir)

- **Dispatcher** (este módulo): invoca handlers síncronos **dentro del
  proceso**. P. ej.: "cuando se crea un Customer -> enviar email de bienvenida
  (síncrono, transaccionalmente atómico con el commit si se desea)". Los
  handlers van en código Python in-process. No hay redes, no hay bus.
- **Publisher** (``events/publisher.py``): port hacia integración externa.
  Puede tener un backend de Outbox físico, Kafka, Redis Streams, etc.

## Regla Gate 0.2 de semántica

Despachamos handlers **solo después** de un UnitOfWork.commit exitoso. Jamás
antes. Este módulo no se protege a sí mismo contra invocaciones pre-commit;
es responsabilidad del orquestador de use cases (ver ``execution/use_case.py``)
garantizar el orden correcto. Documentamos la regla aquí para futuros
implementadores.

## Orden de resolución de handlers

Registro es explícito por tipo de evento. Para un evento ``e: CustomerCreated``:

1. Iteramos MRO de ``type(e)`` hasta ``DomainEvent`` (incluido), sin ``object``.
2. Por cada tipo en MRO (más específico primero), disparamos handlers
   registrados en el orden de registro.

Así, un handler registrado para ``DomainEvent`` se dispara para **todos** los
eventos. No hay deduplicación automática si registras el mismo handler varias
veces (cada invocación cuenta).

## Comportamiento sin handlers

No-op. No se lanza error. El dispatcher de Gate 0.2 es permisivo por defecto.
Si requieres comportamiento estricto, hereda o envuelve y valida.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Generic, Protocol, TypeVar, runtime_checkable

from universal_business.application.errors import ApplicationError
from universal_business.domain.shared.events import DomainEvent

EventT = TypeVar("EventT", bound=DomainEvent, contravariant=True)


@runtime_checkable
class DomainEventHandler(Protocol, Generic[EventT]):
    """Handler interno síncrono para un DomainEvent concreto.

    Firma estructural::

        def handle(self, event: EventT) -> None: ...
    """

    def handle(self, event: EventT) -> None:
        raise NotImplementedError


class DomainEventDispatcher:
    """Coordinador lógico de DomainEvent → handlers síncronos.

    Registro explícito por tipo (no hay autodiscovery). Orden determinista
    = orden de registro dentro de cada tipo.
    """

    def __init__(self) -> None:
        # tipo de evento → lista[handler]
        self._registry: dict[type[DomainEvent], list[DomainEventHandler[DomainEvent]]] = {}

    # ------------------------------------------------------------------
    # Registro
    # ------------------------------------------------------------------

    def register(
        self,
        event_type: type[DomainEvent],
        handler: DomainEventHandler[DomainEvent],
        /,
    ) -> None:
        """Registra un handler para un tipo de evento concreto (o DomainEvent
        genérico para aplicar a todos).

        Parámetros posicionales-only para evitar confusión en orden.
        """
        if not isinstance(event_type, type) or not issubclass(event_type, DomainEvent):
            raise ApplicationError(
                f"DomainEventDispatcher.register: event_type debe ser una subclase "
                f"de DomainEvent, got {event_type!r}"
            )
        # No validamos runtime check de handler; Protocol lo hace en isinstance si es
        # que se construye un adapter. Aquí aceptamos duck typing sin introspección.
        self._registry.setdefault(event_type, []).append(handler)

    # ------------------------------------------------------------------
    # Resolución
    # ------------------------------------------------------------------

    def _resolve_handlers(self, event: DomainEvent) -> list[DomainEventHandler[DomainEvent]]:
        """Resuelve handlers siguiendo MRO (más específico → genérico)."""
        out: list[DomainEventHandler[DomainEvent]] = []
        for t in type(event).__mro__:
            if t is object:
                break
            if not issubclass(t, DomainEvent):
                continue
            hs = self._registry.get(t)
            if hs:
                out.extend(hs)
        return out

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def dispatch(self, event: DomainEvent, /) -> None:
        """Dispara handlers sincronos para *event* en orden determinista.

        Cualquier excepción levantada por un handler se **propaga tal cual**.
        No se capturan silenciosamente. El orquestador del use case decide
        si las excepciones de handlers internos hacen fallar la transacción
        (post-commit: la transacción ya fue committeada).

        Comportamiento sin handlers: no-op.
        """
        if not isinstance(event, DomainEvent):
            raise ApplicationError(
                "DomainEventDispatcher.dispatch: argumento no es DomainEvent, "
                f"got {type(event).__name__}"
            )
        for h in self._resolve_handlers(event):
            h.handle(event)

    def dispatch_many(self, events: Iterable[DomainEvent], /) -> None:
        """Equivalente a ``for e in events: dispatch(e)`` en el mismo orden.

        Nótese que *events* se materializa a list antes de iterar, para detectar
        y rechazar elementos NO-DomainEvent de forma eager (antes de invocar
        cualquier handler).
        """
        materialized: list[DomainEvent] = list(events)
        for idx, e in enumerate(materialized):
            if not isinstance(e, DomainEvent):
                raise ApplicationError(
                    "DomainEventDispatcher.dispatch_many: el elemento "
                    f"#{idx} no es DomainEvent (got={type(e).__name__}). "
                    "Ningún handler fue invocado todavía."
                )
        for e in materialized:
            self.dispatch(e)


__all__ = [
    "DomainEventDispatcher",
    "DomainEventHandler",
    "EventT",
]
