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
OutT = TypeVar("OutT")


@runtime_checkable
class UseCaseHandler(Protocol, Generic[InT, OutT]):
    """Handler orquestacional de un caso de uso concreto.

    La implementación es **responsabilidad de fases 0.3/0.4+**. En Gate 0.2 solo
    definimos la firma estructural del patrón mínimo.

    Firma canónica::

        def handle(self, input: InT) -> tuple[OutT, Sequence[DomainEvent]]: ...

    El segundo elemento de la tupla es la colección de DomainEvent ya
    recolectados de los aggregates afectados. Vacía si no hubo cambios.

    ## Hooks opcionales de ciclo de vida (Gate 0.3)

    *post_commit_success* y *post_rollback* son callbacks opcionales invocados
    por :func:`execute_use_case` SÓLO en el escenario indicado. Los handlers
    idempotentes (CreateOffering, CreateResource, etc.) los usan para:

    - ``post_commit_success`` → ``IdempotencyStore.complete()`` (después de commit).
    - ``post_rollback`` → ``IdempotencyStore.release()`` (tras excepción en handle o commit).

    Handlers que no necesiten estos hooks simplemente NO los implementan; el
    protocolo sigue siendo structural.
    """

    def handle(self, input: InT, /) -> tuple[OutT, Sequence[DomainEvent]]:
        raise NotImplementedError

    def post_commit_success(self, result: OutT, /) -> None:
        """Hook opcional: ejecuta **solo si** ``uow.commit()`` retornó sin error."""

    def post_rollback(self, exc: BaseException, /) -> None:
        """Hook opcional: ejecuta si handle() lanza o commit() lanza (antes raise)."""


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
    events_holder: dict[str, Sequence[DomainEvent]] = {}
    result_holder: dict[str, OutT] = {}
    exc_holder: dict[str, BaseException] = {}
    try:
        with unit_of_work as uow:
            result, events = handler.handle(input)
            result_holder["r"] = result
            # Permitir override (por lo general, se usa None; tests lo aprovechan).
            if _collector_override is not None:
                events = list(_collector_override(result, events))
            events_holder["e"] = events
            uow.commit()
    except BaseException as e:  # noqa: BLE001 - rollback semantics
        exc_holder["x"] = e
        # Hook de post-rollback (si existe):
        if hasattr(handler, "post_rollback"):
            try:
                handler.post_rollback(e)
            except Exception:  # noqa: BLE001 - hook failure never masks original
                pass
        raise
    # ---- Post-commit: aquí el uow.__exit__ ya corrió y no lanzó error ----
    # Hook de post_commit_success (si existe): IdempotencyStore.complete() etc.
    if hasattr(handler, "post_commit_success"):
        try:
            handler.post_commit_success(result_holder["r"])
        except Exception as hook_exc:
            # Commit ya se consolidó; no hay rollback posible pero sí se reporta.
            # En Gate 0.3 no atrapamos: propagamos para que el flujo lo note,
            # sin perder events.
            try:
                events_list = list(events_holder.get("e", []))
                if events_list:
                    event_dispatcher.dispatch_many(events_list)
                    event_publisher.publish_many(events_list)
            finally:
                raise hook_exc
    events_list = list(events_holder.get("e", []))
    if events_list:
        event_dispatcher.dispatch_many(events_list)
        event_publisher.publish_many(events_list)
    return result_holder["r"]


__all__ = [
    "InT",
    "OutT",
    "UseCaseHandler",
    "execute_use_case",
]
