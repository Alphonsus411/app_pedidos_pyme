"""Primitivas temporales: DateRange, TimeRange y guardias timezone-aware.

NINGÚN datetime naive (tzinfo=None) debe cruzar el límite del dominio.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Self

from universal_business.domain.shared.errors import (
    TemporalRangeError,
    TimezoneAwareRequiredError,
)

UTC = dt.UTC


def require_aware(value: dt.datetime, *, field_name: str = "datetime") -> dt.datetime:
    """Valida que value sea timezone-aware. Lanza TimezoneAwareRequiredError si no.

    NUNCA normaliza tzinfo=None a UTC bajo silencio: la omisión de zona en los
    bordes del dominio es un bug del llamador, no una convención aceptable.
    """
    if not isinstance(value, dt.datetime):
        raise TemporalRangeError(
            f"{field_name}: se esperaba datetime, recibido {type(value).__name__}"
        )
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise TimezoneAwareRequiredError(
            f"{field_name}= debe ser timezone-aware (tzinfo no None). Recibido naive: {value!r}"
        )
    return value


def to_utc(value: dt.datetime) -> dt.datetime:
    """Convierte un dt aware a UTC con zona explícita."""
    require_aware(value)
    return value.astimezone(UTC)


@dataclass(frozen=True)
class DateRange:
    """Rango de fechas (date, no datetime). Inclusivo en ambos extremos.

    Para periodos que incluyen horas usa TimeRange.
    """

    start: dt.date
    end: dt.date

    def __post_init__(self) -> None:
        if not isinstance(self.start, dt.date) or isinstance(self.start, dt.datetime):
            raise TemporalRangeError(f"DateRange.start debe ser datetime.date: {self.start!r}")
        if not isinstance(self.end, dt.date) or isinstance(self.end, dt.datetime):
            raise TemporalRangeError(f"DateRange.end debe ser datetime.date: {self.end!r}")
        if self.start > self.end:
            raise TemporalRangeError(
                f"DateRange.start ({self.start.isoformat()}) "
                f"posterior a end ({self.end.isoformat()})"
            )

    @classmethod
    def single(cls, d: dt.date) -> Self:
        return cls(start=d, end=d)

    @classmethod
    def from_iso(cls, start_iso: str, end_iso: str) -> Self:
        return cls(
            start=dt.date.fromisoformat(start_iso),
            end=dt.date.fromisoformat(end_iso),
        )

    def __contains__(self, item: object) -> bool:
        if isinstance(item, dt.date) and not isinstance(item, dt.datetime):
            return self.start <= item <= self.end
        if isinstance(item, DateRange):
            return self.start <= item.start and item.end <= self.end
        return False

    def overlaps(self, other: DateRange) -> bool:
        return self.start <= other.end and other.start <= self.end

    def intersection(self, other: DateRange) -> Self | None:
        if not self.overlaps(other):
            return None
        return type(self)(start=max(self.start, other.start), end=min(self.end, other.end))

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def __str__(self) -> str:
        return f"[{self.start.isoformat()}..{self.end.isoformat()}]"


@dataclass(frozen=True)
class TimeRange:
    """Rango [start, end) o [start, end] según interpretación; aquí inclusivo en ambos.

    Ambos extremos SIEMPRE son timezone-aware. Internamente se normalizan a UTC
    pero se conserva el datetime original para representación.
    """

    start: dt.datetime
    end: dt.datetime

    def __post_init__(self) -> None:
        require_aware(self.start, field_name="TimeRange.start")
        require_aware(self.end, field_name="TimeRange.end")
        if self.start > self.end:
            raise TemporalRangeError(
                "TimeRange.start posterior a end: "
                f"{self.start.isoformat()} > {self.end.isoformat()}"
            )

    @classmethod
    def between(cls, start: dt.datetime, end: dt.datetime) -> Self:
        return cls(start=start, end=end)

    @classmethod
    def from_iso(cls, start_iso: str, end_iso: str) -> Self:
        s = dt.datetime.fromisoformat(start_iso)
        e = dt.datetime.fromisoformat(end_iso)
        return cls(start=s, end=e)

    @property
    def start_utc(self) -> dt.datetime:
        return to_utc(self.start)

    @property
    def end_utc(self) -> dt.datetime:
        return to_utc(self.end)

    def __contains__(self, item: object) -> bool:
        if isinstance(item, dt.datetime):
            require_aware(item)
            return self.start <= item <= self.end
        if isinstance(item, TimeRange):
            return self.start <= item.start and item.end <= self.end
        return False

    def overlaps(self, other: TimeRange) -> bool:
        return self.start <= other.end and other.start <= self.end

    def intersection(self, other: TimeRange) -> Self | None:
        if not self.overlaps(other):
            return None
        return type(self)(start=max(self.start, other.start), end=min(self.end, other.end))

    @property
    def duration(self) -> dt.timedelta:
        return self.end - self.start

    def __str__(self) -> str:
        return f"[{self.start.isoformat()} .. {self.end.isoformat()}]"


__all__ = [
    "require_aware",
    "to_utc",
    "UTC",
    "DateRange",
    "TimeRange",
]
