"""Ventana configurable de llegada, sin valores predeterminados."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from universal_business.application.errors import ApplicationError
from universal_business.domain.reservations.entities import Reservation
from universal_business.domain.shared.value_objects.temporal import TimeRange


@dataclass(frozen=True, kw_only=True)
class CheckInWindowPolicy:
    """Permitir llegada en [inicio-anticipación, inicio+retraso], ambos inclusivos.

    El negocio debe configurar ambos plazos y el reloj; la comparación usa UTC.
    No valida autorización del actor ni coordina esta ventana con NO_SHOW.
    """

    clock: Callable[[], datetime]
    early: timedelta
    late: timedelta

    def __post_init__(self) -> None:
        if not callable(self.clock):
            raise ApplicationError("Se requiere un reloj invocable")
        if any(
            not isinstance(value, timedelta) or value < timedelta(0)
            for value in (self.early, self.late)
        ):
            raise ApplicationError("Los plazos deben ser duraciones no negativas")

    def approve(self, *, reservation: Reservation) -> bool:
        if not isinstance(reservation.time_range, TimeRange):
            raise ApplicationError("Intervalo de reserva inválido")
        now = self.clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ApplicationError("El reloj debe devolver un datetime con zona horaria")
        try:
            start = reservation.time_range.start.astimezone(UTC)
            instant = now.astimezone(UTC)
            return start - self.early <= instant <= start + self.late
        except (OverflowError, ValueError) as exc:
            raise ApplicationError("No se pudo calcular la ventana de llegada") from exc
