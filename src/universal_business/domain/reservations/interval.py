"""Intervalos de reserva semiabiertos, independientes de TimeRange inclusivo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from universal_business.domain.shared.errors import TemporalRangeError
from universal_business.domain.shared.value_objects.temporal import to_utc


@dataclass(frozen=True)
class ReservationInterval:
    """Intervalo de instantes [start, end), normalizado a UTC.

    Requiere datetimes conscientes y duración positiva. La resolución de horas
    locales ambiguas o inexistentes corresponde a la frontera que interpreta
    la agenda; este tipo solo compara instantes ya especificados.
    """

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        start = to_utc(self.start)
        end = to_utc(self.end)
        if start >= end:
            raise TemporalRangeError("ReservationInterval requiere start anterior a end")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    def overlaps(self, other: ReservationInterval) -> bool:
        """Los intervalos contiguos no se solapan."""
        if not isinstance(other, ReservationInterval):
            raise TypeError("other debe ser ReservationInterval")
        return self.start < other.end and other.start < self.end

    def contains(self, instant: datetime) -> bool:
        """Inicio incluido; fin excluido. El instante debe ser aware."""
        value = to_utc(instant)
        return self.start <= value < self.end
