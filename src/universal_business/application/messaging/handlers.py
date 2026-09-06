"""Contratos tipados para handlers.

Se elige :class:`typing.Protocol` (structural subtyping) y **no** ABC por
las siguientes razones:

1. Permite fakes en tests sin necesidad de ``register`` ni herencia.
2. No fuerza un árbol de clases (un handler puede ser una función, una
   instancia con ``handle``, o un módulo con callable — Protocols admiten
   cualquiera que cuadre estructuralmente).
3. Sigue el mismo patrón que los Repository Ports en Gate 0.1.

No hay registry global, no hay bus, no hay service locator. El código
orquestador pasa los handlers que necesita por constructor o argumento
posicional/keyword; la resolución es siempre explícita.
"""

from __future__ import annotations

from typing import Generic, Protocol, TypeVar, runtime_checkable

from universal_business.application.messaging.commands import Command
from universal_business.application.messaging.queries import Query

CommandT = TypeVar("CommandT", bound=Command, covariant=False, contravariant=True)
QueryT = TypeVar("QueryT", bound=Query, covariant=False, contravariant=True)
ResultT = TypeVar("ResultT", covariant=True)


@runtime_checkable
class CommandHandler(Protocol, Generic[CommandT, ResultT]):
    """Handler genérico para un command concreto.

    Firma estructural::

        def handle(self, command: CommandT) -> ResultT: ...
    """

    def handle(self, command: CommandT) -> ResultT:
        """Ejecuta el command y devuelve su resultado."""
        raise NotImplementedError


@runtime_checkable
class QueryHandler(Protocol, Generic[QueryT, ResultT]):
    """Handler genérico para una query concreta.

    Firma estructural::

        def handle(self, query: QueryT) -> ResultT: ...
    """

    def handle(self, query: QueryT) -> ResultT:
        """Ejecuta la query y devuelve su resultado."""
        raise NotImplementedError


__all__ = [
    "CommandHandler",
    "CommandT",
    "QueryHandler",
    "QueryT",
    "ResultT",
]
