"""Retirada idempotente de líneas de pedidos."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from uuid import UUID

from universal_business.application.errors import ApplicationError, IdempotencyConflictError
from universal_business.application.execution import ExecutionHooks, IdempotentReplay
from universal_business.application.idempotency import (
    IdempotencyKey,
    IdempotencyStore,
    scoped_idempotency_key,
)
from universal_business.application.orders.commands import RemoveOrderLine
from universal_business.application.request_digest import request_digest
from universal_business.domain.orders.events import OrderLineRemoved
from universal_business.domain.orders.mutation import OrderMutationGuard
from universal_business.domain.orders.ports import IOrderRepository
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    OrderId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money


@dataclass(frozen=True, kw_only=True)
class OrderLineRemoval:
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    order_id: OrderId
    line_id: UUID
    total: Money | None


def _key(command: RemoveOrderLine) -> IdempotencyKey:
    if not isinstance(command.idempotency_key, IdempotencyKey):
        raise ApplicationError("Se requiere una clave de idempotencia válida")
    return scoped_idempotency_key(
        business_id=command.business_id,
        operation=f"{type(command).__module__}.{type(command).__qualname__}",
        key=command.idempotency_key,
    )


class RemoveOrderLineHandler:
    """Guard y repositorio comparten UoW; autorizar al actor en frontera incluso en replay."""

    def __init__(
        self, *, orders: IOrderRepository, guard: OrderMutationGuard, idempotency: IdempotencyStore
    ) -> None:
        self._orders, self._guard, self._idempotency = orders, guard, idempotency

    def handle(self, command: RemoveOrderLine, /) -> tuple[OrderLineRemoval, Sequence[DomainEvent]]:
        if not all(
            (
                isinstance(command.tenant_id, TenantId),
                isinstance(command.business_id, BusinessId),
                isinstance(command.location_id, LocationId),
                isinstance(command.order_id, OrderId),
                isinstance(command.line_id, UUID),
            )
        ):
            raise ApplicationError("Identificadores o ámbito inválidos")
        key, digest, tid = _key(command), request_digest(command), command.tenant_id
        if not self._idempotency.reserve(tid, key, digest):
            cached = self._idempotency.get(tid, key)
            if (
                cached is not None
                and cached[0] == digest
                and isinstance(cached[1], OrderLineRemoval)
            ):
                result = cached[1]
                if (
                    result.tenant_id,
                    result.business_id,
                    result.location_id,
                    result.order_id,
                    result.line_id,
                ) == (
                    tid,
                    command.business_id,
                    command.location_id,
                    command.order_id,
                    command.line_id,
                ):
                    return IdempotentReplay(result)
            raise IdempotencyConflictError("Idempotency conflict or request in progress")
        try:
            self._guard.protect(
                tenant_id=tid,
                business_id=command.business_id,
                location_id=command.location_id,
                order_id=command.order_id,
            )
            order = self._orders.get(tenant_id=tid, order_id=command.order_id)
            if order is None or (
                order.tenant_id,
                order.business_id,
                order.location_id,
                order.id,
            ) != (tid, command.business_id, command.location_id, command.order_id):
                raise ApplicationError("Order no encontrado o fuera del ámbito")
            line = next((line for line in order.lines if line.line_id == command.line_id), None)
            if line is None:
                raise ApplicationError("Línea de pedido inexistente")
            updated = replace(order)
            updated.remove_line(command.line_id)
            self._orders.save(updated)
            result = OrderLineRemoval(
                tenant_id=tid,
                business_id=command.business_id,
                location_id=command.location_id,
                order_id=command.order_id,
                line_id=command.line_id,
                total=updated.total,
            )
            event = OrderLineRemoved(
                aggregate_id=command.order_id,
                tenant_id=tid,
                business_id=command.business_id,
                location_id=command.location_id,
                offering_id=line.offering_id,
                line_id=command.line_id,
            )
            return result, [event]
        except BaseException:
            try:
                self._idempotency.release(tid, key)
            except Exception:
                pass
            raise

    def build_hooks(
        self, input: RemoveOrderLine, result: OrderLineRemoval, /
    ) -> ExecutionHooks[OrderLineRemoval]:
        key, digest, tid = _key(input), request_digest(input), input.tenant_id

        def success(_result: OrderLineRemoval) -> None:
            self._idempotency.complete(tid, key, digest, result)

        def failure(_exc: BaseException) -> None:
            self._idempotency.release(tid, key)

        return ExecutionHooks(on_success=success, on_failure=failure)
