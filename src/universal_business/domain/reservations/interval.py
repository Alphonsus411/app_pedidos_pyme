"""Intervalos de reserva semiabiertos, independientes de TimeRange inclusivo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from universal_business.domain.reservations.local_time import resolve_local_datetime
from universal_business.domain.shared.errors import TemporalRangeError
from universal_business.domain.shared.value_objects.temporal import to_utc


@dataclass(frozen=True)
class ReservationInterval:
    """Intervalo de instantes [start, end), normalizado a UTC.

    Requiere datetimes conscientes y duración positiva. La resolución de horas
    locales ambiguas o inexistentes se ofrece mediante from_local; el
    constructor directo recibe instantes ya interpretados.
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

    @classmethod
    def from_local(
        cls,
        start: datetime,
        end: datetime,
        zone: ZoneInfo,
        *,
        start_fold: int | None = None,
        end_fold: int | None = None,
    ) -> ReservationInterval:
        """Resolver extremos locales y construir el intervalo semiabierto."""
        return cls(
            resolve_local_datetime(start, zone, fold=start_fold),
            resolve_local_datetime(end, zone, fold=end_fold),
        )

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
