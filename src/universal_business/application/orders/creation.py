"""Creación idempotente de pedidos en borrador."""

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
from universal_business.application.orders.commands import CreateOrder
from universal_business.application.request_digest import request_digest
from universal_business.domain.business.ports import ILocationRepository
from universal_business.domain.business.value_objects import LocationStatus
from universal_business.domain.customers.ports import ICustomerRepository
from universal_business.domain.orders.entities import Order
from universal_business.domain.orders.events import OrderCreated
from universal_business.domain.orders.ports import IOrderRepository
from universal_business.domain.orders.value_objects import OrderChannel, OrderStatus
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CustomerId,
    LocationId,
    OrderId,
    TenantId,
)


@dataclass(frozen=True, kw_only=True)
class OrderDraftCreated:
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    order_id: OrderId


def _key(command: CreateOrder) -> IdempotencyKey:
    if not isinstance(command.idempotency_key, IdempotencyKey):
        raise ApplicationError("Se requiere una clave de idempotencia válida")
    return scoped_idempotency_key(
        business_id=command.business_id,
        operation=f"{type(command).__module__}.{type(command).__qualname__}",
        key=command.idempotency_key,
    )


class CreateOrderHandler:
    """Guardar borrador vacío; debe ejecutarse mediante execute_use_case.

    Repositorios y UnitOfWork deben compartir transacción; el adaptador debe
    garantizar unicidad del ID ante creaciones simultáneas. La autorización,
    persistencia durable y política de operaciones no están implementadas aquí.
    """

    def __init__(
        self,
        *,
        orders: IOrderRepository,
        locations: ILocationRepository,
        customers: ICustomerRepository,
        idempotency: IdempotencyStore,
    ) -> None:
        self._orders, self._locations, self._customers = orders, locations, customers
        self._idempotency = idempotency

    def handle(self, command: CreateOrder, /) -> tuple[OrderDraftCreated, Sequence[DomainEvent]]:
        if not isinstance(command.tenant_id, TenantId) or not isinstance(
            command.business_id, BusinessId
        ):
            raise ApplicationError("Ámbito tenant/business inválido")
        if not isinstance(command.location_id, LocationId):
            raise ApplicationError("Identificador de ubicación inválido")
        key, digest, tid = _key(command), request_digest(command), command.tenant_id
        if not self._idempotency.reserve(tid, key, digest):
            cached = self._idempotency.get(tid, key)
            if (
                cached is not None
                and cached[0] == digest
                and isinstance(cached[1], OrderDraftCreated)
            ):
                result = cached[1]
                if (result.tenant_id, result.business_id, result.location_id, result.order_id) == (
                    tid,
                    command.business_id,
                    command.location_id,
                    command.order_id,
                ):
                    return IdempotentReplay(result)
            raise IdempotencyConflictError("Idempotency conflict or request in progress")
        try:
            if not isinstance(command.channel, OrderChannel):
                raise ApplicationError("Canal de pedido inválido")
            if not isinstance(command.order_id, OrderId):
                raise ApplicationError("Identificador de pedido inválido")
            if command.customer_id is not None and not isinstance(command.customer_id, CustomerId):
                raise ApplicationError("Identificador de cliente inválido")
            if self._orders.get(tenant_id=tid, order_id=command.order_id) is not None:
                raise ApplicationError("Order ya existe")
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
            if command.customer_id is not None:
                customer = self._customers.get(
                    tenant_id=tid, business_id=command.business_id, customer_id=command.customer_id
                )
                if customer is None or (customer.tenant_id, customer.business_id, customer.id) != (
                    tid,
                    command.business_id,
                    command.customer_id,
                ):
                    raise ApplicationError("Customer no encontrado o fuera del ámbito")
            order = Order(
                id=command.order_id,
                tenant_id=tid,
                business_id=command.business_id,
                location_id=command.location_id,
                status=OrderStatus.DRAFT,
                channel=command.channel,
                customer_id=command.customer_id,
            )
            self._orders.save(order)
            result = OrderDraftCreated(
                tenant_id=tid,
                business_id=command.business_id,
                location_id=command.location_id,
                order_id=command.order_id,
            )
            event = OrderCreated(
                aggregate_id=command.order_id,
                tenant_id=tid,
                business_id=command.business_id,
                location_id=command.location_id,
            )
            return result, [event]
        except BaseException:
            try:
                self._idempotency.release(tid, key)
            except Exception:
                pass
            raise

    def build_hooks(
        self, input: CreateOrder, result: OrderDraftCreated, /
    ) -> ExecutionHooks[OrderDraftCreated]:
        key, digest, tid = _key(input), request_digest(input), input.tenant_id

        def success(_result: OrderDraftCreated) -> None:
            self._idempotency.complete(tid, key, digest, result)

        def failure(_exc: BaseException) -> None:
            self._idempotency.release(tid, key)

        return ExecutionHooks(on_success=success, on_failure=failure)
