"""Construcción coordinada de políticas temporales de reserva."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from universal_business.application.errors import ApplicationError
from universal_business.application.reservations.check_in_policy import CheckInWindowPolicy
from universal_business.application.reservations.no_show_policy import GracePeriodNoShowPolicy


@dataclass(frozen=True, kw_only=True)
class ReservationTimingPolicies:
    """Crear políticas con mismo reloj y ventanas que no se solapan.

    Ambas políticas incluyen su extremo, por lo que la gracia de no-show debe
    ser estrictamente mayor que el retraso de check-in. Puede quedar un hueco
    en el que ninguna transición esté permitida; el negocio elige los plazos.
    Las políticas construidas por separado no se validan mediante esta clase.
    """

    clock: Callable[[], datetime]
    early: timedelta
    late: timedelta
    grace_period: timedelta
    check_in: CheckInWindowPolicy = field(init=False)
    no_show: GracePeriodNoShowPolicy = field(init=False)

    def __post_init__(self) -> None:
        arrival = CheckInWindowPolicy(clock=self.clock, early=self.early, late=self.late)
        no_show = GracePeriodNoShowPolicy(clock=self.clock, grace_period=self.grace_period)
        if self.grace_period <= self.late:
            raise ApplicationError("El plazo de no presentación debe superar el de llegada")
        object.__setattr__(self, "check_in", arrival)
        object.__setattr__(self, "no_show", no_show)
