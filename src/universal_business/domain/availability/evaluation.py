"""Evaluación de disponibilidad sobre ventanas y bloqueos ya materializados."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from universal_business.domain.reservations.conflicts import conflicting_reservation_ids
from universal_business.domain.reservations.entities import Reservation
from universal_business.domain.reservations.interval import ReservationInterval
from universal_business.domain.resources.entities import Resource
from universal_business.domain.resources.value_objects import ResourceStatus
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    ReservationId,
    ResourceId,
    TenantId,
)


@dataclass(frozen=True)
class AvailabilityScope:
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    resource_id: ResourceId

    def __post_init__(self) -> None:
        if not (
            isinstance(self.tenant_id, TenantId)
            and isinstance(self.business_id, BusinessId)
            and isinstance(self.location_id, LocationId)
            and isinstance(self.resource_id, ResourceId)
        ):
            raise InvariantViolationError("Ámbito de disponibilidad inválido")


@dataclass(frozen=True)
class ScopedAvailabilityPeriod:
    """Ventana o bloqueo concreto; no expande reglas recurrentes ni DateRange."""

    scope: AvailabilityScope
    interval: ReservationInterval

    def __post_init__(self) -> None:
        if not isinstance(self.scope, AvailabilityScope) or not isinstance(
            self.interval, ReservationInterval
        ):
            raise InvariantViolationError("Ventana o bloqueo inválido")


class AvailabilityReason(StrEnum):
    AVAILABLE = "available"
    INACTIVE_RESOURCE = "inactive_resource"
    CAPACITY_EXCEEDED = "capacity_exceeded"
    OUTSIDE_WINDOWS = "outside_windows"
    BLOCKED = "blocked"
    RESERVATION_CONFLICT = "reservation_conflict"


@dataclass(frozen=True)
class AvailabilityEvaluation:
    reason: AvailabilityReason
    conflict_ids: tuple[ReservationId, ...] = ()

    @property
    def available(self) -> bool:
        return self.reason == AvailabilityReason.AVAILABLE


def _periods(
    scope: AvailabilityScope, periods: Iterable[ScopedAvailabilityPeriod]
) -> list[ReservationInterval]:
    result = []
    for period in periods:
        if not isinstance(period, ScopedAvailabilityPeriod) or period.scope != scope:
            raise InvariantViolationError("Ventana o bloqueo fuera del ámbito")
        result.append(period.interval)
    return result


def _covered(requested: ReservationInterval, windows: list[ReservationInterval]) -> bool:
    cursor = requested.start
    for window in sorted(windows, key=lambda item: (item.start, item.end)):
        if window.end <= cursor:
            continue
        if window.start > cursor:
            return False
        cursor = max(cursor, window.end)
        if cursor >= requested.end:
            return True
    return False


def evaluate_availability(
    *,
    scope: AvailabilityScope,
    resource: Resource,
    requested: ReservationInterval,
    windows: Iterable[ScopedAvailabilityPeriod],
    blocks: Iterable[ScopedAvailabilityPeriod],
    reservations: Iterable[Reservation],
    party_size: int | None = None,
) -> AvailabilityEvaluation:
    """Evaluar datos concretos, sin reservar recursos ni consultar repositorios.

    Sin ventanas se rechaza. Los bloqueos tienen prioridad sobre ventanas y
    reservas; intervalos contiguos no se solapan. Solo acepta un recurso
    asignado a la location consultada. Reglas recurrentes, zonas y expansión
    de fechas se resuelven fuera de esta función. Para confirmar se necesita
    una adjudicación atómica transaccional; esta lectura puede quedar obsoleta.
    """
    if not isinstance(scope, AvailabilityScope) or not isinstance(requested, ReservationInterval):
        raise InvariantViolationError("Ámbito o intervalo solicitado inválido")
    if not isinstance(resource, Resource) or (
        resource.tenant_id != scope.tenant_id
        or resource.business_id != scope.business_id
        or resource.id != scope.resource_id
        or resource.location_id != scope.location_id
    ):
        raise InvariantViolationError("Recurso fuera del ámbito o sin location asignada")
    if not isinstance(resource.status, ResourceStatus):
        raise InvariantViolationError("Estado de recurso inválido")
    if resource.capacity is not None and (
        type(resource.capacity) is not int or resource.capacity < 0
    ):
        raise InvariantViolationError("Capacidad de recurso inválida")
    if party_size is not None and (type(party_size) is not int or party_size <= 0):
        raise InvariantViolationError("party_size debe ser entero positivo")

    # Validate all input scopes even if an earlier condition rejects availability.
    window_intervals = _periods(scope, windows)
    block_intervals = _periods(scope, blocks)
    conflict_ids = conflicting_reservation_ids(
        tenant_id=scope.tenant_id,
        business_id=scope.business_id,
        location_id=scope.location_id,
        resource_id=scope.resource_id,
        interval=requested,
        reservations=reservations,
    )
    if resource.status != ResourceStatus.ACTIVE:
        return AvailabilityEvaluation(AvailabilityReason.INACTIVE_RESOURCE)
    if party_size is not None and resource.capacity is not None and party_size > resource.capacity:
        return AvailabilityEvaluation(AvailabilityReason.CAPACITY_EXCEEDED)
    if any(block.overlaps(requested) for block in block_intervals):
        return AvailabilityEvaluation(AvailabilityReason.BLOCKED)
    if not _covered(requested, window_intervals):
        return AvailabilityEvaluation(AvailabilityReason.OUTSIDE_WINDOWS)
    if conflict_ids:
        return AvailabilityEvaluation(AvailabilityReason.RESERVATION_CONFLICT, conflict_ids)
    return AvailabilityEvaluation(AvailabilityReason.AVAILABLE)
