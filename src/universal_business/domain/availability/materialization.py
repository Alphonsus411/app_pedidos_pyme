"""Conversión explícita y conservadora de reglas legacy a intervalos concretos."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from universal_business.domain.availability.entities import AvailabilityBlock, AvailabilityRule
from universal_business.domain.availability.evaluation import (
    AvailabilityScope,
    ScopedAvailabilityPeriod,
)
from universal_business.domain.availability.value_objects import AvailabilityStatus
from universal_business.domain.business.entities import Location
from universal_business.domain.reservations.interval import ReservationInterval
from universal_business.domain.reservations.local_time import resolve_local_datetime
from universal_business.domain.shared.errors import InvariantViolationError, TemporalRangeError
from universal_business.domain.shared.value_objects.ids import ResourceId
from universal_business.domain.shared.value_objects.temporal import DateRange, TimeRange


def _date_interval(value: DateRange, zone: ZoneInfo) -> ReservationInterval:
    """Fechas inclusivas en zona local convertidas a [medianoche, día siguiente)."""
    if not isinstance(value, DateRange):
        raise InvariantViolationError("Rango de fechas inválido")
    try:
        end = value.end + timedelta(days=1)
    except OverflowError as exc:
        raise TemporalRangeError("No se puede convertir el final del rango de fechas") from exc
    start_utc = resolve_local_datetime(datetime.combine(value.start, time.min), zone)
    end_utc = resolve_local_datetime(datetime.combine(end, time.min), zone)
    return ReservationInterval(start_utc, end_utc)


def _within_scope(scope: AvailabilityScope, tenant: object, location: object) -> None:
    if tenant != scope.tenant_id or location != scope.location_id:
        raise InvariantViolationError("Regla o bloqueo fuera del tenant/location solicitado")


def materialize_availability_periods(
    *,
    scope: AvailabilityScope,
    location: Location,
    rules: Iterable[AvailabilityRule],
    blocks: Iterable[AvailabilityBlock],
) -> tuple[tuple[ScopedAvailabilityPeriod, ...], tuple[ScopedAvailabilityPeriod, ...]]:
    """Convertir reglas y bloqueos a periodos concretos para la evaluación pura.

    Una regla contiene instantes explícitos, no horarios recurrentes. Para esta
    operación se interpretan los extremos de TimeRange como [inicio, fin) y se
    recortan al DateRange efectivo de la location; no se altera TimeRange.
    Bloqueos DateRange cubren fechas locales completas, ambos días inclusivos.
    Rechaza reglas con capacidad específica, aún sin semántica implementada.
    Un recurso diferente dentro del mismo tenant/location no se aplica. Medianoche
    local ambigua o inexistente falla en vez de inferir un instante.
    Esta conversión no consulta almacenamiento ni garantiza atomicidad.
    """
    if not isinstance(scope, AvailabilityScope) or not isinstance(location, Location):
        raise InvariantViolationError("Ámbito o location inválido")
    if (location.tenant_id, location.business_id, location.id) != (
        scope.tenant_id,
        scope.business_id,
        scope.location_id,
    ):
        raise InvariantViolationError("Location fuera del ámbito solicitado")
    try:
        zone = ZoneInfo(location.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvariantViolationError("Zona horaria de location no disponible o inválida") from exc

    windows: list[ScopedAvailabilityPeriod] = []
    blocked: list[ScopedAvailabilityPeriod] = []
    for rule in rules:
        if not isinstance(rule, AvailabilityRule):
            raise InvariantViolationError("Regla de disponibilidad inválida")
        _within_scope(scope, rule.tenant_id, rule.location_id)
        if not isinstance(rule.status, AvailabilityStatus):
            raise InvariantViolationError("Estado de regla inválido")
        if rule.resource_id is not None and not isinstance(rule.resource_id, ResourceId):
            raise InvariantViolationError("Recurso de regla inválido")
        if rule.status == AvailabilityStatus.INACTIVE or rule.resource_id not in (
            None,
            scope.resource_id,
        ):
            continue
        if rule.capacity is not None:
            raise InvariantViolationError("La capacidad por regla todavía no está soportada")
        effective = _date_interval(rule.effective_range, zone)
        for raw in rule.time_ranges:
            if not isinstance(raw, TimeRange):
                raise InvariantViolationError("Intervalo de regla inválido")
            actual = ReservationInterval(raw.start, raw.end)
            start, end = max(actual.start, effective.start), min(actual.end, effective.end)
            if start < end:
                windows.append(ScopedAvailabilityPeriod(scope, ReservationInterval(start, end)))
    for block in blocks:
        if not isinstance(block, AvailabilityBlock):
            raise InvariantViolationError("Bloqueo de disponibilidad inválido")
        _within_scope(scope, block.tenant_id, block.location_id)
        if not isinstance(block.status, AvailabilityStatus):
            raise InvariantViolationError("Estado de bloqueo inválido")
        if block.resource_id is not None and not isinstance(block.resource_id, ResourceId):
            raise InvariantViolationError("Recurso de bloqueo inválido")
        if block.status == AvailabilityStatus.INACTIVE or block.resource_id not in (
            None,
            scope.resource_id,
        ):
            continue
        blocked.append(ScopedAvailabilityPeriod(scope, _date_interval(block.blocked_range, zone)))
    return tuple(windows), tuple(blocked)
