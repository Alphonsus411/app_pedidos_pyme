"""Política configurable para no presentación de reservas."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from universal_business.application.errors import ApplicationError
from universal_business.domain.reservations.entities import Reservation
from universal_business.domain.shared.value_objects.temporal import TimeRange


@dataclass(frozen=True, kw_only=True)
class GracePeriodNoShowPolicy:
    """Permitir NO_SHOW desde inicio + gracia, comparando instantes UTC.

    Tanto el reloj como la duración son obligatorios; no existe plazo por
    defecto. La configuración debe ser aprobada por el negocio. No autentica
    ni autoriza al actor y no consulta la hora en replays ya completados.
    """

    clock: Callable[[], datetime]
    grace_period: timedelta

    def __post_init__(self) -> None:
        if not callable(self.clock):
            raise ApplicationError("Se requiere un reloj invocable")
        if not isinstance(self.grace_period, timedelta) or self.grace_period < timedelta(0):
            raise ApplicationError("El plazo de cortesía debe ser una duración no negativa")

    def approve(self, *, reservation: Reservation) -> bool:
        if not isinstance(reservation.time_range, TimeRange):
            raise ApplicationError("Intervalo de reserva inválido")
        now = self.clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ApplicationError("El reloj debe devolver un datetime con zona horaria")
        try:
            deadline = reservation.time_range.start.astimezone(UTC) + self.grace_period
            return now.astimezone(UTC) >= deadline
        except (OverflowError, ValueError) as exc:
            raise ApplicationError("No se pudo calcular el plazo de no presentación") from exc
