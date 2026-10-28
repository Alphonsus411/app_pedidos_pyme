"""Cancelación idempotente protegida de reservas."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from universal_business.application.errors import ApplicationError, IdempotencyConflictError
from universal_business.application.execution import ExecutionHooks, IdempotentReplay
from universal_business.application.idempotency import (
    IdempotencyKey,
    IdempotencyStore,
    scoped_idempotency_key,
)
from universal_business.application.request_digest import request_digest
from universal_business.application.reservations.commands import CancelReservation
from universal_business.application.reservations.handlers import _snapshot
from universal_business.domain.reservations.allocation import ReservationMutationGuard
from universal_business.domain.reservations.entities import Reservation
from universal_business.domain.reservations.events import ReservationCancelled
from universal_business.domain.reservations.lifecycle import validate_reservation_transition
from universal_business.domain.reservations.ports import IReservationRepository
from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    ReservationId,
    ResourceId,
    TenantId,
)


@dataclass(frozen=True, kw_only=True)
class ReservationCancellation:
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    reservation_id: ReservationId
    resource_id: ResourceId


def _key(command: CancelReservation) -> IdempotencyKey:
    if not isinstance(command.idempotency_key, IdempotencyKey):
        raise ApplicationError("Se requiere una clave de idempotencia válida")
    return scoped_idempotency_key(
        business_id=command.business_id,
        operation=f"{type(command).__module__}.{type(command).__qualname__}",
        key=command.idempotency_key,
    )


def _in_scope(reservation: Reservation, command: CancelReservation) -> None:
    if (
        reservation.tenant_id,
        reservation.business_id,
        reservation.location_id,
        reservation.id,
    ) != (command.tenant_id, command.business_id, command.location_id, command.reservation_id):
        raise ApplicationError("Reservation fuera del ámbito solicitado")


class CancelReservationHandler:
    """Cancelar dentro de execute_use_case con guard y repositorio de la misma UoW.

    El guard debe coordinarse con confirmación y demás mutaciones hasta el fin
    de la transacción. Los adaptadores reales deben validar esa garantía.
    """

    def __init__(
        self,
        *,
        reservations: IReservationRepository,
        guard: ReservationMutationGuard,
        idempotency: IdempotencyStore,
    ) -> None:
        self._reservations, self._guard, self._idempotency = reservations, guard, idempotency

    def handle(
        self, command: CancelReservation, /
    ) -> tuple[ReservationCancellation, Sequence[DomainEvent]]:
        key, digest, tid = _key(command), request_digest(command), command.tenant_id
        if not self._idempotency.reserve(tid, key, digest):
            cached = self._idempotency.get(tid, key)
            if (
                cached is not None
                and cached[0] == digest
                and isinstance(cached[1], ReservationCancellation)
            ):
                result = cached[1]
                if (
                    result.tenant_id,
                    result.business_id,
                    result.location_id,
                    result.reservation_id,
                ) == (tid, command.business_id, command.location_id, command.reservation_id):
                    return IdempotentReplay(result)
            raise IdempotencyConflictError("Idempotency conflict or request in progress")
        try:
            initial = self._reservations.get(tenant_id=tid, reservation_id=command.reservation_id)
            if initial is None:
                raise ApplicationError("Reservation no encontrada")
            _in_scope(initial, command)
            validate_reservation_transition(initial.status, ReservationStatus.CANCELLED)
            snapshot = _snapshot(initial)
            self._guard.protect(
                tenant_id=tid,
                business_id=command.business_id,
                location_id=command.location_id,
                resource_id=initial.resource_id,
                reservation_id=initial.id,
            )
            current = self._reservations.get(tenant_id=tid, reservation_id=command.reservation_id)
            if current is None:
                raise ApplicationError("Reservation ya no existe")
            _in_scope(current, command)
            if _snapshot(current) != snapshot:
                raise ApplicationError("Reservation cambió durante la cancelación")
            cancelled = replace(current, status=ReservationStatus.CANCELLED)
            cancelled.touch()
            self._reservations.save(cancelled)
            result = ReservationCancellation(
                tenant_id=tid,
                business_id=command.business_id,
                location_id=command.location_id,
                reservation_id=current.id,
                resource_id=current.resource_id,
            )
            event = ReservationCancelled(
                aggregate_id=current.id,
                tenant_id=tid,
                business_id=command.business_id,
                location_id=command.location_id,
                resource_id=current.resource_id,
            )
            return result, [event]
        except BaseException:
            try:
                self._idempotency.release(tid, key)
            except Exception:
                pass
            raise

    def build_hooks(
        self, input: CancelReservation, result: ReservationCancellation, /
    ) -> ExecutionHooks[ReservationCancellation]:
        key, digest, tid = _key(input), request_digest(input), input.tenant_id

        def success(_result: ReservationCancellation) -> None:
            self._idempotency.complete(tid, key, digest, result)

        def failure(_exc: BaseException) -> None:
            self._idempotency.release(tid, key)

        return ExecutionHooks(on_success=success, on_failure=failure)
