"""Creación idempotente de reservas en borrador, sin adjudicación."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from universal_business.application.errors import ApplicationError, IdempotencyConflictError
from universal_business.application.execution import ExecutionHooks, IdempotentReplay
from universal_business.application.idempotency import (
    IdempotencyKey,
    IdempotencyStore,
    scoped_idempotency_key,
)
from universal_business.application.request_digest import request_digest
from universal_business.application.reservations.commands import CreateReservation
from universal_business.domain.business.ports import ILocationRepository
from universal_business.domain.business.value_objects import LocationStatus
from universal_business.domain.customers.ports import ICustomerRepository
from universal_business.domain.reservations.entities import Reservation
from universal_business.domain.reservations.events import ReservationCreated
from universal_business.domain.reservations.interval import ReservationInterval
from universal_business.domain.reservations.ports import IReservationRepository
from universal_business.domain.resources.ports import IResourceRepository
from universal_business.domain.resources.value_objects import ResourceStatus
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    ReservationId,
    ResourceId,
    TenantId,
)
from universal_business.domain.shared.value_objects.temporal import TimeRange


@dataclass(frozen=True, kw_only=True)
class ReservationDraftCreated:
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    reservation_id: ReservationId
    resource_id: ResourceId


def _key(command: CreateReservation) -> IdempotencyKey:
    if not isinstance(command.idempotency_key, IdempotencyKey):
        raise ApplicationError("Se requiere una clave de idempotencia válida")
    return scoped_idempotency_key(
        business_id=command.business_id,
        operation=f"{type(command).__module__}.{type(command).__qualname__}",
        key=command.idempotency_key,
    )


class CreateReservationHandler:
    """Guardar borrador sin ocupar recursos; ejecutar mediante execute_use_case.

    Los repositorios y la UoW deben compartir transacción. Las validaciones de
    esta creación no reemplazan la adjudicación atómica al confirmar. El
    adaptador debe garantizar unicidad del ID incluso ante creación concurrente.
    """

    def __init__(
        self,
        *,
        reservations: IReservationRepository,
        customers: ICustomerRepository,
        locations: ILocationRepository,
        resources: IResourceRepository,
        idempotency: IdempotencyStore,
    ) -> None:
        self._reservations, self._customers, self._locations = reservations, customers, locations
        self._resources, self._idempotency = resources, idempotency

    def handle(
        self, command: CreateReservation, /
    ) -> tuple[ReservationDraftCreated, Sequence[DomainEvent]]:
        key, digest, tid = _key(command), request_digest(command), command.tenant_id
        if not self._idempotency.reserve(tid, key, digest):
            cached = self._idempotency.get(tid, key)
            if (
                cached is not None
                and cached[0] == digest
                and isinstance(cached[1], ReservationDraftCreated)
            ):
                result = cached[1]
                if (
                    result.tenant_id,
                    result.business_id,
                    result.location_id,
                    result.reservation_id,
                    result.resource_id,
                ) == (
                    tid,
                    command.business_id,
                    command.location_id,
                    command.reservation_id,
                    command.resource_id,
                ):
                    return IdempotentReplay(result)
            raise IdempotencyConflictError("Idempotency conflict or request in progress")
        try:
            if not isinstance(command.interval, ReservationInterval):
                raise ApplicationError("Intervalo de reserva inválido")
            if command.party_size is not None and (
                type(command.party_size) is not int or command.party_size <= 0
            ):
                raise ApplicationError("party_size debe ser entero positivo")
            existing = self._reservations.get(tenant_id=tid, reservation_id=command.reservation_id)
            if existing is not None:
                raise ApplicationError("Reservation ya existe")
            location = self._locations.get(
                tenant_id=tid, business_id=command.business_id, location_id=command.location_id
            )
            if location is None or (location.tenant_id, location.business_id, location.id) != (
                tid,
                command.business_id,
                command.location_id,
            ):
                raise ApplicationError("Location no encontrada o fuera del ámbito")
            if (
                not isinstance(location.status, LocationStatus)
                or location.status != LocationStatus.OPEN
            ):
                raise ApplicationError("Location no está abierta")
            resource = self._resources.get(
                tenant_id=tid, business_id=command.business_id, resource_id=command.resource_id
            )
            if resource is None or (
                resource.tenant_id,
                resource.business_id,
                resource.location_id,
                resource.id,
            ) != (tid, command.business_id, command.location_id, command.resource_id):
                raise ApplicationError("Resource no encontrado o fuera del ámbito")
            if (
                not isinstance(resource.status, ResourceStatus)
                or resource.status != ResourceStatus.ACTIVE
            ):
                raise ApplicationError("Resource no está activo")
            if resource.capacity is not None and (
                type(resource.capacity) is not int or resource.capacity < 0
            ):
                raise ApplicationError("Capacidad de recurso inválida")
            if (
                command.party_size is not None
                and resource.capacity is not None
                and command.party_size > resource.capacity
            ):
                raise ApplicationError("Capacidad de recurso excedida")
            customer = self._customers.get(
                tenant_id=tid, business_id=command.business_id, customer_id=command.customer_id
            )
            if customer is None or (customer.tenant_id, customer.business_id, customer.id) != (
                tid,
                command.business_id,
                command.customer_id,
            ):
                raise ApplicationError("Customer no encontrado o fuera del ámbito")
            reservation = Reservation(
                id=command.reservation_id,
                tenant_id=tid,
                business_id=command.business_id,
                location_id=command.location_id,
                resource_id=command.resource_id,
                customer_id=command.customer_id,
                time_range=TimeRange(command.interval.start, command.interval.end),
                party_size=command.party_size,
                notes=command.notes,
            )
            self._reservations.save(reservation)
            result = ReservationDraftCreated(
                tenant_id=tid,
                business_id=command.business_id,
                location_id=command.location_id,
                reservation_id=command.reservation_id,
                resource_id=command.resource_id,
            )
            event = ReservationCreated(
                aggregate_id=command.reservation_id,
                tenant_id=tid,
                business_id=command.business_id,
                location_id=command.location_id,
                resource_id=command.resource_id,
            )
            return result, [event]
        except BaseException:
            try:
                self._idempotency.release(tid, key)
            except Exception:
                pass
            raise

    def build_hooks(
        self, input: CreateReservation, result: ReservationDraftCreated, /
    ) -> ExecutionHooks[ReservationDraftCreated]:
        key, digest, tid = _key(input), request_digest(input), input.tenant_id

        def success(_result: ReservationDraftCreated) -> None:
            self._idempotency.complete(tid, key, digest, result)

        def failure(_exc: BaseException) -> None:
            self._idempotency.release(tid, key)

        return ExecutionHooks(on_success=success, on_failure=failure)
