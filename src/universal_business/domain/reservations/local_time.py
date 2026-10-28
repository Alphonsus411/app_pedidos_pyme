"""Interpretación explícita de horas locales para solicitudes de reserva."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from universal_business.domain.shared.errors import TemporalRangeError


def resolve_local_datetime(local: datetime, zone: ZoneInfo, *, fold: int | None = None) -> datetime:
    """Interpretar una hora local naive en una zona IANA, devolviendo un instante UTC.

    Las horas inexistentes se rechazan. Si la hora se repite, el caller debe
    elegir fold=0 o fold=1 explícitamente. Para horas no ambiguas ambos valores
    identifican el mismo instante. No se infiere una zona a partir del sistema.
    """
    if not isinstance(local, datetime) or local.tzinfo is not None:
        raise TemporalRangeError("La hora local debe ser datetime sin zona")
    if not isinstance(zone, ZoneInfo):
        raise TypeError("zone debe ser ZoneInfo de una zona IANA")
    if fold is not None and (type(fold) is not int or fold not in (0, 1)):
        raise ValueError("fold debe ser 0, 1 o None")

    candidates: dict[int, datetime] = {}
    for candidate_fold in (0, 1):
        candidate = local.replace(tzinfo=zone, fold=candidate_fold).astimezone(UTC)
        roundtrip = candidate.astimezone(zone)
        if roundtrip.replace(tzinfo=None) == local.replace(fold=0):
            candidates[candidate_fold] = candidate

    if not candidates:
        raise TemporalRangeError("La hora local no existe en esta zona")
    if len(set(candidates.values())) > 1 and fold is None:
        raise TemporalRangeError("La hora local es ambigua; indicar fold=0 o fold=1")
    selected_fold = 0 if fold is None else fold
    if selected_fold not in candidates:
        raise TemporalRangeError("El fold indicado no corresponde a una hora local válida")
    return candidates[selected_fold]
