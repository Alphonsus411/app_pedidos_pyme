"""Utilidades compartidas para máquinas de estado finitas.

IMPORTANTE (Corrección 2): NO existe un enumerado LifecycleStatus único.
Cada módulo define SU propio XxxStatus(str, Enum). Aquí sólo vive la
primitiva genérica de validación.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar

from universal_business.domain.shared.errors import StatusTransitionError

S = TypeVar("S", bound=Enum)

StatusTransitions = dict[S, set[S]]


@dataclass(frozen=True)
class StatusTransition(Generic[S]):
    """Helper inmutable: matriz de transiciones permitidas por agregado.

    Cada agregado construye una instancia con su matriz propia (p. ej.
    `OrderStatus` vs `ReservationStatus`) y la usa en sus métodos de
    mutación para validar transiciones antes de aplicarlas.
    """

    valid_transitions: StatusTransitions[S]

    def can(self, from_: S, to: S) -> bool:
        return to in self.valid_transitions.get(from_, set())

    def ensure(self, from_: S, to: S) -> None:
        if not self.can(from_, to):
            allowed = sorted(x.value for x in self.valid_transitions.get(from_, set()))
            raise StatusTransitionError(
                f"Transición inválida: {from_.value} -> {to.value}. "
                f"Permitido desde {from_.value}: {allowed if allowed else 'ninguna'}"
            )


def transition_guard(current: S, target: S, matrix: StatusTransitions[S]) -> None:
    """Alias funcional rápido. Útil cuando no se quiere instanciar la clase."""
    StatusTransition(matrix).ensure(current, target)


__all__ = [
    "StatusTransitions",
    "StatusTransition",
    "transition_guard",
]
