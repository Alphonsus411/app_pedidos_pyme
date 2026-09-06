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
    3.  Construye ``ExecutionHooks`` POR-EJECUCIÓN (stateless) llamando a
        ``handler.build_hooks(input, resultado)`` si el handler implementa
        :class:`UseCaseHandlerWithExecutionHooks`. En este punto los
        closures ``on_success`` / ``on_failure`` capturan toda la info que
        necesitan (key idempotency, store, digests…).
    4.  ``uow.commit()`` — solo aquí se consolidan los cambios.
    5.  Si commit() NO lanzó error:
          a. Hooks on_success de ExecutionHooks (si los hay) — p. ej. IdempotencyStore.complete()
          b. ``dispatcher.dispatch_many(events_collected)``
          c. ``publisher.publish_many(events_collected)``
    6.  Devuelve ``resultado``.

### En caso de error

- Si handler lanza excepción → ``__exit__`` recibe exc → rollback; se invocan
  hooks legacy ``PostRollbackHook``; los STATLESS handlers usan ``on_failure``
  que ya capturaron en el mismo ``handle()`` (ver más abajo). NO se
  despacha/publica nada.
- Si commit() lanza error → excepción propagada; rollback automático; se
  invocan ``ExecutionHooks.on_failure`` (si existen) y/o legacy
  ``PostRollbackHook``; NO se despacha/publica nada.
- Si un hook on_success lanza error después de commit:
  Ver :ref:`complete-failure-semantics` más abajo.

## Hooks per-ejecución (STATELESS — Gate 0.3)

Los hooks de ciclo de vida YA NO se guardan en ``self`` del handler (eso creaba
estado mutable compartido entre ejecuciones concurrentes sobre la misma
instancia). En su lugar existe el protocolo opcional
:class:`UseCaseHandlerWithExecutionHooks` cuyo método ``build_hooks`` devuelve
un objeto inmutable :class:`ExecutionHooks` con ``on_success`` / ``on_failure``
como **closures** que pertenecen EXCLUSIVAMENTE a esa ejecución concreta.

``build_hooks`` se llama **dentro** de la transacción (antes de ``uow.commit``)
para que ``on_failure`` quede listo si el commit falla. El closure
``on_failure`` captura toda la información que necesita (``store``,
``tenant_id``, ``idempotency_key``…) sin depender de ``self._idem_pending``.

.. _complete-failure-semantics:

## Complete failure semantics (IdempotencyStore.complete)

Si ``store.complete()`` (llamado desde el hook on_success) lanza DESPUÉS de
que ``uow.commit()`` haya retornado OK:

  - El dominio (UoW) YA ESTÁ COMMITTEADO — no hay rollback posible.
  - La idempotency key PERMANECE en estado ``RESERVED``. **NO** se invoca
    ``store.release()``: eso permitiría a una segunda ejecución reservar la
    misma key y crear un duplicado del aggregate.
  - El error de ``complete()`` se PROPAGA hacia arriba. El sistema queda en
    estado indeterminado post-commit que requiere reconciliación manual.
  - Los ``DomainEvent`` **SÍ** se despachan y publican antes de propagar el
    error: el dominio fue committeado y los eventos deben fluir.
  - Importante: ``commit() + complete()`` **NO** son atómicos. Este diseño
    elige *consistencia eventual con seguridad sobre duplicados* en lugar de
    intentar una atomicidad imposible entre dos sistemas separados.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar, runtime_checkable

from universal_business.application.events.dispatcher import DomainEventDispatcher
from universal_business.application.events.publisher import EventPublisher
from universal_business.application.idempotency import IdempotencyKey, IdempotencyStore
from universal_business.application.unit_of_work import UnitOfWork
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import TenantId

InT = TypeVar("InT", covariant=False, contravariant=True)
OutT = TypeVar("OutT")
OutT_co = TypeVar("OutT_co", covariant=True)
OutT_contra = TypeVar("OutT_contra", contravariant=True)


@runtime_checkable
class UseCaseHandler(Protocol, Generic[InT, OutT_co]):
    """Handler orquestacional de un caso de uso concreto.

    La implementación es **responsabilidad de fases 0.3/0.4+**. En Gate 0.2 solo
    definimos la firma estructural del patrón mínimo.

    Firma canónica::

        def handle(self, input: InT) -> tuple[OutT, Sequence[DomainEvent]]: ...

    El segundo elemento de la tupla es la colección de DomainEvent ya
    recolectados de los aggregates afectados. Vacía si no hubo cambios.

    Este protocolo NO incluye hooks: los hooks opcionales viven en
    :class:`UseCaseHandlerWithExecutionHooks` (un protocol separado para que
    el structural typing no los convierta en métodos requeridos).
    """

    def handle(self, input: InT, /) -> tuple[OutT_co, Sequence[DomainEvent]]:
        raise NotImplementedError


@runtime_checkable
class PostCommitSuccessHook(Protocol, Generic[OutT_contra]):
    """Protocol separado (opcional) para handlers antiguos que usan el estilo
    ``post_commit_success``. Existe por compatibilidad; el estilo NUEVO y
    preferido es :class:`UseCaseHandlerWithExecutionHooks` + ``build_hooks``.
    """

    def post_commit_success(self, result: OutT_contra, /) -> None: ...


@runtime_checkable
class PostRollbackHook(Protocol):
    """Protocol separado (opcional) para handlers antiguos que usan el estilo
    ``post_rollback``. Existe por compatibilidad; el estilo NUEVO y preferido
    es :class:`UseCaseHandlerWithExecutionHooks` + ``build_hooks``.
    """

    def post_rollback(self, exc: BaseException, /) -> None: ...


@dataclass(frozen=True)
class IdempotencyExecutionState:
    """Estado inmutable POR-EJECUCIÓN para idempotencia.

    NUNCA se guarda una instancia de esta clase como atributo del handler
    (eso crearía estado mutable compartido). Las instancias se capturan
    dentro de closures de :class:`ExecutionHooks` y mueren al terminar
    la ejecución concreta.
    """

    store: IdempotencyStore
    tenant_id: TenantId
    idempotency_key: IdempotencyKey
    result_digest: str
    result_for_complete: object | None = None


@dataclass(frozen=True)
class ExecutionHooks(Generic[OutT]):
    """Contenedor inmutable de callbacks por-ejecución.

    Cada invocación a ``execute_use_case`` genera SU PROPIO ``ExecutionHooks``
    vía ``handler.build_hooks(...)`` justo después de ``handle()`` y ANTES de
    ``uow.commit()``. Los closures ``on_success`` / ``on_failure`` capturan
    el estado de esa ejecución y NUNCA tocan atributos mutables del handler.
    """

    on_success: Callable[[OutT], None] | None = None
    on_failure: Callable[[BaseException], None] | None = None


@runtime_checkable
class UseCaseHandlerWithExecutionHooks(Protocol, Generic[InT, OutT]):
    """Extensión opcional y STATLESS de :class:`UseCaseHandler`.

    Los handlers que necesitan hooks per-ejecución (idempotencia, outbox
    auxiliar, métricas, etc.) implementan ESTE protocolo. ``build_hooks``
    recibe el ``input`` y el ``result`` YA calculados de la ejecución
    concreta y devuelve un :class:`ExecutionHooks` inmutable con los
    callbacks. El handler INSTANCIA NUNCA guarda nada en ``self`` entre
    ``handle()`` y el commit.
    """

    def handle(self, input: InT, /) -> tuple[OutT, Sequence[DomainEvent]]: ...

    def build_hooks(
        self,
        input: InT,
        result: OutT,
        /,
    ) -> ExecutionHooks[OutT] | None: ...


def _dispatch_and_publish_safe(
    events_list: list[DomainEvent],
    event_dispatcher: DomainEventDispatcher,
    event_publisher: EventPublisher,
) -> None:
    if events_list:
        event_dispatcher.dispatch_many(events_list)
        event_publisher.publish_many(events_list)


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
    """Helper de ejecución: aplica el flujo canónico descrito arriba.

    Todos los params son keyword-only para evitar errores de orden.

    Parámetros
    ----------
    _collector_override:
        Opcional. Si se pasa, permite *transformar* la lista events del
        handler (p. ej. para añadir metadata a posteriori) antes de
        dispatch/publish. Útil en tests y en extensiones de verticales.
        ``None`` (default) = usar la lista tal cual devolvió el handler.

    Hooks (nuevo flujo STATLESS)
    ----------------------------
    Dentro de la transacción (antes de commit):
      1. ``handler.handle(input)`` → result, events.
      2. Si ``handler`` implementa ``UseCaseHandlerWithExecutionHooks``:
         ``hooks = handler.build_hooks(input, result)``; guardado en un
         holder para usarlo en rollback y post-commit.
    En rollback:
      3. Si existe ``hooks.on_failure`` → invocar; además invocar legacy
         ``PostRollbackHook`` si el handler lo implementa. Raise.
    Post-commit:
      4. ``hooks.on_success(result)`` + legacy ``PostCommitSuccessHook``.
         Si este hook lanza → complete failure semantics (events sí, no release,
         propagar exc).
      5. dispatch + publish events.
    """
    events_holder: dict[str, Sequence[DomainEvent]] = {}
    result_holder: dict[str, OutT] = {}
    hooks_holder: dict[str, ExecutionHooks[OutT] | None] = {"h": None}
    try:
        with unit_of_work as uow:
            result, events = handler.handle(input)
            result_holder["r"] = result
            if _collector_override is not None:
                events = list(_collector_override(result, events))
            events_holder["e"] = events
            # Construir hooks DENTRO de la transacción, ANTES del commit.
            # Así on_failure queda listo si commit lanza.
            if isinstance(handler, UseCaseHandlerWithExecutionHooks):
                hooks_holder["h"] = handler.build_hooks(input, result)
            uow.commit()
    except BaseException as e:  # noqa: BLE001 - rollback semantics
        hooks = hooks_holder["h"]
        if hooks is not None and hooks.on_failure is not None:
            try:
                hooks.on_failure(e)
            except Exception:  # noqa: BLE001 - hook failure never masks original
                pass
        if isinstance(handler, PostRollbackHook):
            try:
                handler.post_rollback(e)
            except Exception:  # noqa: BLE001 - hook failure never masks original
                pass
        raise

    # ---- Post-commit: uow.__exit__ ya corrió sin error ----
    result_val = result_holder["r"]
    events_list = list(events_holder.get("e", []))
    hooks = hooks_holder["h"]
    try:
        if hooks is not None and hooks.on_success is not None:
            hooks.on_success(result_val)
        if isinstance(handler, PostCommitSuccessHook):
            handler.post_commit_success(result_val)
    except Exception as hook_exc:
        # Complete failure semantics: dominio commit OK, hook falló.
        # - NO rollback (imposible).
        # - NO release (la key debe quedar RESERVED para evitar duplicados).
        # - SÍ dispatch + publish (los eventos son parte del dominio confirmado).
        # - Finalmente propagar hook_exc.
        _dispatch_and_publish_safe(events_list, event_dispatcher, event_publisher)
        raise hook_exc
    _dispatch_and_publish_safe(events_list, event_dispatcher, event_publisher)
    return result_val


__all__ = [
    "InT",
    "OutT",
    "UseCaseHandler",
    "PostCommitSuccessHook",
    "PostRollbackHook",
    "IdempotencyExecutionState",
    "ExecutionHooks",
    "UseCaseHandlerWithExecutionHooks",
    "execute_use_case",
]
