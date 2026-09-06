"""Primitivas de ejecución de casos de uso (orquestación). Gate 0.2 Foundation.

Patrón mínimo que une: UnitOfWork + DomainEventDispatcher + EventPublisher + handler
de orquestación. NO introduce dependencias externas. NO introduce CQRS buses,
NO introduce mediadores, NO introduce registries.

## Flujo canónico de ejecución (regla de Gate 0.2 no negociable)

Sea un ``UseCaseHandler[InT, OutT]`` que toma input y devuelve una tupla
``(resultado: OutT, events_to_dispatch: Sequence[DomainEvent])``::

    1.  Entra en UnitOfWork (context manager).
    2.  Ejecuta ``use_case_handler.handle(input)`` que produce
        ``(resultado, events_collected)``.
    3.  ``uow.commit()`` — solo aquí se consolidan los cambios.
    4.  Si commit() NO lanzó error:
          a. ``dispatcher.dispatch_many(events_collected)``
          b. ``publisher.publish_many(events_collected)``
    5.  Devuelve ``resultado``.

### En caso de error

- Si handler lanza excepción → ``__exit__`` recibe exc → rollback; NO se
  despacha/publica nada.
- Si commit() lanza error → excepción propagada; rollback automático; NO se
  despacha/publica nada.
- Si un handler del dispatcher lanza error después de commit: la excepción
  se propaga tal cual, pero el UoW ya está committeado
  (documentado: "el dispatch post-commit no atómico").

## Por qué devuelve events_collected el use case handler

Porque los DomainEvent se generan dentro del dominio en cada aggregate vía
:class:`AggregateRootMixin.add_domain_event`. El orquestador (use case handler)
es quien tiene acceso a los aggregates modificados y es responsable de
agregar los ``aggregate.domain_events`` en una lista. El helper de ejecución
asume que ya se recolectaron (no hace introspección mágica de aggregates).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Generic, Protocol, TypeVar, runtime_checkable

from universal_business.application.events.dispatcher import DomainEventDispatcher
from universal_business.application.events.publisher import EventPublisher
from universal_business.application.unit_of_work import UnitOfWork
from universal_business.domain.shared.events import DomainEvent

InT = TypeVar("InT", covariant=False, contravariant=True)
OutT = TypeVar("OutT", covariant=True)


@runtime_checkable
class UseCaseHandler(Protocol, Generic[InT, OutT]):
    """Handler orquestacional de un caso de uso concreto.

    La implementación es **responsabilidad de fases 0.3/0.4+**. En Gate 0.2 solo
    definimos la firma estructural del patrón mínimo.

    Firma canónica::

        def handle(self, input: InT) -> tuple[OutT, Sequence[DomainEvent]]: ...

    El segundo elemento de la tupla es la colección de DomainEvent ya
    recolectados de los aggregates afectados. Vacía si no hubo cambios.
    """

    def handle(self, input: InT, /) -> tuple[OutT, Sequence[DomainEvent]]:
        raise NotImplementedError


def execute_use_case(
    *,
    handler: UseCaseHandler[InT, OutT],
    input: InT,
    unit_of_work: UnitOfWork,
    event_dispatcher: DomainEventDispatcher,
    event_publisher: EventPublisher,
    _collector_override: (
        Callable[[OutT, Sequence[DomainEvent]], Sequence[DomainEvent]] | None
    ) = None,
) -> OutT:
    """Helper de ejecución: aplica el flujo canónico 1..5 descrito arriba.

    Todos los params son keyword-only para evitar errores de orden.

    Parámetros
    ----------
    _collector_override:
        Opcional. Si se pasa, permite *transformar* la lista events del
        handler (p. ej. para añadir metadata a posteriori) antes de
        dispatch/publish. Útil en tests y en extensiones de verticales.
        ``None`` (default) = usar la lista tal cual devolvió el handler.
    """
    with unit_of_work as uow:
        result, events = handler.handle(input)
        # Permitir override (por lo general, se usa None; tests lo aprovechan).
        if _collector_override is not None:
            events = list(_collector_override(result, events))
        uow.commit()
    # ---- Post-commit: aquí el uow.__exit__ ya corrió y no lanzó error ----
    events_list = list(events)
    if events_list:
        event_dispatcher.dispatch_many(events_list)
        event_publisher.publish_many(events_list)
    return result


__all__ = [
    "InT",
    "OutT",
    "UseCaseHandler",
    "execute_use_case",
]
