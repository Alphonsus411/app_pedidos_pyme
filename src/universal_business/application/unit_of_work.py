"""UnitOfWork — port de frontera transaccional lógica.

Gate 0.2 NO implementa ningún motor de persistencia real (SQLAlchemy, etc.).
:class:`UnitOfWork` es simplemente un Protocol que describe **cómo** se debe
comportar la frontera:

1. ``__enter__``: abre el ámbito transaccional (equivalente a begin()).
2. Se ejecuta la lógica de dominio/orquestación (capa de aplicación).
3. Se llama a :meth:`commit` **explícitamente** si todo fue OK.
4. ``__exit__``: ante una excepción o ausencia de commit, intenta rollback.
   Un rollback posterior no demuestra que un commit incierto no se aplicó.

**No hay commit implícito por ``__exit__``.** Se elige esto en vez de "commit
cuando no hay error" para minimizar los commits accidentales y dejar muy
explícita la decisión de persistir (AC-R-26).

Semántica de publicación de eventos (ver ADR-008 y ADR-009):
Solo **después** de un :meth:`commit` con éxito se permite:
- despachar los DomainEvent a handlers síncronos internos,
- publicar los DomainEvent al port externo :class:`EventPublisher`.
Jamás antes, y jamás si hubo :meth:`rollback`.
"""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, Self, runtime_checkable


class CommitNotAppliedError(RuntimeError):
    """The adapter guarantees the attempted commit had no durable effect.

    Raise only when this guarantee is known. Other exceptions from commit
    represent an unknown outcome and require reconciliation.
    """


@runtime_checkable
class UnitOfWork(Protocol):
    """Port (Protocol) de Unidad de Trabajo.

    Los adapters reales (Gate 0.5+) implementarán esto sobre transacciones
    DB reales, sesiones HTTP, o múltiples repositorios coordinados. El core
    no sufre acoplamiento porque todo se pasa por :pep:`544` Protocol.

    Diseño para Gate 0.2: **sin savepoints, sin anidamiento explícito, sin flush**.
    Las versiones futuras pueden añadir miembros sin romper BC porque los
    Protocol aceptan implementaciones con métodos extra.
    """

    # ------------------------------------------------------------------
    # Context manager (principio RAII)
    # ------------------------------------------------------------------

    def __enter__(self) -> Self:
        """Entra en el ámbito transaccional. Equivalente a begin()."""
        raise NotImplementedError

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
        /,
    ) -> None:
        """Sale del ámbito.

        Semántica (no negociable):

        - Si ``exc is not None`` → rollback automático. La excepción se
          propaga (devuelve False implícitamente).
        - Si ``exc is None`` pero :meth:`commit` nunca fue llamado →
          rollback automático (cambio parcial no confirmado).
        - Si :meth:`commit` fue llamado → no-op; la transacción ya se
          consolidó y no hay nada que limpiar.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Operaciones explícitas
    # ------------------------------------------------------------------

    def commit(self) -> None:
        """Consolida la transacción lógica.

        El adaptador solo puede lanzar CommitNotAppliedError si sabe que no
        hubo commit. Cualquier otra excepción deja el resultado indeterminado:
        no se puede asumir que rollback posterior haya deshecho el commit.

        ``commit()`` múltiples (doble commit) sin operaciones intermedias
        debe ser seguro (idempotente). La semántica específica queda delegada
        a cada implementación concreta; pero se recomienda no lanzar error
        si el estado ya estaba committeado.
        """
        raise NotImplementedError

    def rollback(self) -> None:
        """Deshace la transacción lógica.

        Idempotente. No revierte un commit ya aplicado ni prueba que un
        commit con resultado incierto no se haya aplicado.
        """
        raise NotImplementedError


__all__ = ["CommitNotAppliedError", "UnitOfWork"]
