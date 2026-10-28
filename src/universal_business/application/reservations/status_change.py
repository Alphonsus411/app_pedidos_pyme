"""Cambios protegidos del estado de reservas confirmadas."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Generic, TypeVar

from universal_business.application.errors import ApplicationError, IdempotencyConflictError
from universal_business.application.execution import ExecutionHooks, IdempotentReplay
from universal_business.application.idempotency import (
    IdempotencyKey,
    IdempotencyStore,
    scoped_idempotency_key,
)
from universal_business.application.request_digest import request_digest
from universal_business.application.reservations.commands import (
    CheckInReservation,
    CompleteReservation,
    MarkReservationNoShow,
    ReservationStatusCommand,
)
from universal_business.application.reservations.handlers import _snapshot
from universal_business.domain.reservations.allocation import ReservationMutationGuard
from universal_business.domain.reservations.events import ReservationStatusChanged
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
class ReservationStatusResult:
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    reservation_id: ReservationId
    resource_id: ResourceId
    status: ReservationStatus


C = TypeVar("C", bound=ReservationStatusCommand)


def _key(command: ReservationStatusCommand) -> IdempotencyKey:
    if not isinstance(command.idempotency_key, IdempotencyKey):
        raise ApplicationError("Se requiere una clave de idempotencia válida")
    return scoped_idempotency_key(
        business_id=command.business_id,
        operation=f"{type(command).__module__}.{type(command).__qualname__}",
        key=command.idempotency_key,
    )


class _StatusHandler(Generic[C]):
    """El guard y repositorio deben compartir la UnitOfWork del orquestador.

    No verifica plazos para check-in o no-show; una política de tiempo y
    autorización en la frontera debe definirse antes de exponer estos comandos.
    """

    command_type: type[C]
    target: ReservationStatus

    def __init__(
        self,
        *,
        reservations: IReservationRepository,
        guard: ReservationMutationGuard,
        idempotency: IdempotencyStore,
    ) -> None:
        self._reservations, self._guard, self._idempotency = reservations, guard, idempotency

    def handle(self, command: C, /) -> tuple[ReservationStatusResult, Sequence[DomainEvent]]:
        if type(command) is not self.command_type:
            raise ApplicationError("Tipo de comando no corresponde al handler")
        key, digest, tid = _key(command), request_digest(command), command.tenant_id
        if not self._idempotency.reserve(tid, key, digest):
            cached = self._idempotency.get(tid, key)
            if (
                cached is not None
                and cached[0] == digest
                and isinstance(cached[1], ReservationStatusResult)
            ):
                result = cached[1]
                if (
                    result.tenant_id,
                    result.business_id,
                    result.location_id,
                    result.reservation_id,
                    result.status,
                ) == (
                    tid,
                    command.business_id,
                    command.location_id,
                    command.reservation_id,
                    self.target,
                ):
                    return IdempotentReplay(result)
            raise IdempotencyConflictError("Idempotency conflict or request in progress")
        try:
            initial = self._reservations.get(tenant_id=tid, reservation_id=command.reservation_id)
            if initial is None:
                raise ApplicationError("Reservation no encontrada")
            if (initial.tenant_id, initial.business_id, initial.location_id, initial.id) != (
                tid,
                command.business_id,
                command.location_id,
                command.reservation_id,
            ):
                raise ApplicationError("Reservation fuera del ámbito solicitado")
            validate_reservation_transition(initial.status, self.target)
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
            if (current.tenant_id, current.business_id, current.location_id, current.id) != (
                tid,
                command.business_id,
                command.location_id,
                command.reservation_id,
            ):
                raise ApplicationError("Reservation fuera del ámbito solicitado")
            if _snapshot(current) != snapshot:
                raise ApplicationError("Reservation cambió durante la transición")
            updated = replace(current, status=self.target)
            updated.touch()
            self._reservations.save(updated)
            result = ReservationStatusResult(
                tenant_id=tid,
                business_id=command.business_id,
                location_id=command.location_id,
                reservation_id=current.id,
                resource_id=current.resource_id,
                status=self.target,
            )
            event = ReservationStatusChanged(
                aggregate_id=current.id,
                tenant_id=tid,
                business_id=command.business_id,
                location_id=command.location_id,
                resource_id=current.resource_id,
                previous_status=current.status,
                new_status=self.target,
            )
            return result, [event]
        except BaseException:
            try:
                self._idempotency.release(tid, key)
            except Exception:
                pass
            raise

    def build_hooks(
        self, input: C, result: ReservationStatusResult, /
    ) -> ExecutionHooks[ReservationStatusResult]:
        key, digest, tid = _key(input), request_digest(input), input.tenant_id

        def success(_result: ReservationStatusResult) -> None:
            self._idempotency.complete(tid, key, digest, result)

        def failure(_exc: BaseException) -> None:
            self._idempotency.release(tid, key)

        return ExecutionHooks(on_success=success, on_failure=failure)


class CheckInReservationHandler(_StatusHandler[CheckInReservation]):
    command_type = CheckInReservation
    target = ReservationStatus.CHECKED_IN


class CompleteReservationHandler(_StatusHandler[CompleteReservation]):
    command_type = CompleteReservation
    target = ReservationStatus.COMPLETED


class MarkReservationNoShowHandler(_StatusHandler[MarkReservationNoShow]):
    command_type = MarkReservationNoShow
    target = ReservationStatus.NO_SHOW
