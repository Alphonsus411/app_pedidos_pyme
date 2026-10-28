"""Confirmación de una reserva mediante protección transaccional explícita."""

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
from universal_business.application.reservations.commands import ConfirmReservation
from universal_business.domain.customers.ports import ICustomerRepository
from universal_business.domain.reservations.allocation import ReservationAllocationPort
from universal_business.domain.reservations.entities import Reservation
from universal_business.domain.reservations.events import ReservationConfirmed
from universal_business.domain.reservations.interval import ReservationInterval
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
class ReservationConfirmation:
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    reservation_id: ReservationId
    resource_id: ResourceId


def _key(command: ConfirmReservation) -> IdempotencyKey:
    if not isinstance(command.idempotency_key, IdempotencyKey):
        raise ApplicationError("Se requiere una clave de idempotencia válida")
    return scoped_idempotency_key(
        business_id=command.business_id,
        operation=f"{type(command).__module__}.{type(command).__qualname__}",
        key=command.idempotency_key,
    )


def _snapshot(reservation: Reservation) -> tuple[object, ...]:
    return (
        reservation.id,
        reservation.tenant_id,
        reservation.business_id,
        reservation.location_id,
        reservation.customer_id,
        reservation.resource_id,
        reservation.status,
        ReservationInterval(reservation.time_range.start, reservation.time_range.end),
        reservation.party_size,
    )


def _in_scope(reservation: Reservation, command: ConfirmReservation) -> None:
    if (
        reservation.tenant_id,
        reservation.business_id,
        reservation.location_id,
        reservation.id,
    ) != (command.tenant_id, command.business_id, command.location_id, command.reservation_id):
        raise ApplicationError("Reservation fuera del ámbito solicitado")


class ConfirmReservationHandler:
    """Debe ejecutarse mediante execute_use_case con puertos de la misma UoW.

    El adaptador de adjudicación protege el recurso hasta commit/rollback;
    toda mutación concurrente de la reserva y disponibilidad debe participar
    en protección compatible. Sin adaptador transaccional real no hay garantía
    de concurrencia o durabilidad en producción.
    """

    def __init__(
        self,
        *,
        reservations: IReservationRepository,
        customers: ICustomerRepository,
        allocation: ReservationAllocationPort,
        idempotency: IdempotencyStore,
    ) -> None:
        self._reservations, self._customers = reservations, customers
        self._allocation, self._idempotency = allocation, idempotency

    def handle(
        self, command: ConfirmReservation, /
    ) -> tuple[ReservationConfirmation, Sequence[DomainEvent]]:
        key, digest, tid = _key(command), request_digest(command), command.tenant_id
        if not self._idempotency.reserve(tid, key, digest):
            cached = self._idempotency.get(tid, key)
            if (
                cached is not None
                and cached[0] == digest
                and isinstance(cached[1], ReservationConfirmation)
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
            validate_reservation_transition(initial.status, ReservationStatus.CONFIRMED)
            snapshot = _snapshot(initial)
            if initial.party_size is not None and (
                type(initial.party_size) is not int or initial.party_size <= 0
            ):
                raise ApplicationError("party_size debe ser entero positivo")
            interval = ReservationInterval(initial.time_range.start, initial.time_range.end)
            self._allocation.protect_and_check(
                tenant_id=tid,
                business_id=command.business_id,
                location_id=command.location_id,
                resource_id=initial.resource_id,
                reservation_id=initial.id,
                interval=interval,
                party_size=initial.party_size,
            )
            current = self._reservations.get(tenant_id=tid, reservation_id=command.reservation_id)
            if current is None:
                raise ApplicationError("Reservation ya no existe")
            _in_scope(current, command)
            if _snapshot(current) != snapshot:
                raise ApplicationError("Reservation cambió durante la adjudicación")
            customer = self._customers.get(
                tenant_id=tid, business_id=command.business_id, customer_id=current.customer_id
            )
            if customer is None or (customer.tenant_id, customer.business_id, customer.id) != (
                tid,
                command.business_id,
                current.customer_id,
            ):
                raise ApplicationError("Customer no encontrado o fuera del ámbito")
            confirmed = replace(current, status=ReservationStatus.CONFIRMED)
            confirmed.touch()
            self._reservations.save(confirmed)
            result = ReservationConfirmation(
                tenant_id=tid,
                business_id=command.business_id,
                location_id=command.location_id,
                reservation_id=current.id,
                resource_id=current.resource_id,
            )
            event = ReservationConfirmed(
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
        self, input: ConfirmReservation, result: ReservationConfirmation, /
    ) -> ExecutionHooks[ReservationConfirmation]:
        key, digest, tid = _key(input), request_digest(input), input.tenant_id

        def success(_result: ReservationConfirmation) -> None:
            self._idempotency.complete(tid, key, digest, result)

        def failure(_exc: BaseException) -> None:
            self._idempotency.release(tid, key)

        return ExecutionHooks(on_success=success, on_failure=failure)
