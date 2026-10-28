"""Transiciones idempotentes del ciclo de vida de pedidos."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Generic, Protocol, TypeVar

from universal_business.application.errors import ApplicationError, IdempotencyConflictError
from universal_business.application.execution import ExecutionHooks, IdempotentReplay
from universal_business.application.idempotency import (
    IdempotencyKey,
    IdempotencyStore,
    scoped_idempotency_key,
)
from universal_business.application.orders.commands import (
    CancelOrder,
    CompleteOrder,
    ConfirmOrder,
    DispatchOrder,
    MarkOrderReady,
    OrderStatusCommand,
    PrepareOrder,
    ReturnOrderToDraft,
    ValidateOrder,
)
from universal_business.application.request_digest import request_digest
from universal_business.domain.orders.entities import Order
from universal_business.domain.orders.mutation import OrderMutationGuard
from universal_business.domain.orders.ports import IOrderRepository
from universal_business.domain.orders.value_objects import OrderStatus
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    OrderId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money


class OrderTransitionPolicy(Protocol):
    """Aprobar reglas de negocio externas para la transición; sin política por defecto.

    La frontera autentica y autoriza al actor también antes de cualquier replay.
    El implementador debe fallar de forma conservadora ante incertidumbre.
    """

    def approve(self, *, order: Order, target: OrderStatus) -> bool: ...


@dataclass(frozen=True, kw_only=True)
class OrderStatusResult:
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    order_id: OrderId
    status: OrderStatus
    total: Money | None


def _key(command: OrderStatusCommand) -> IdempotencyKey:
    if not isinstance(command.idempotency_key, IdempotencyKey):
        raise ApplicationError("Se requiere una clave de idempotencia válida")
    return scoped_idempotency_key(
        business_id=command.business_id,
        operation=f"{type(command).__module__}.{type(command).__qualname__}",
        key=command.idempotency_key,
    )


C = TypeVar("C", bound=OrderStatusCommand)


class _Handler(Generic[C]):
    """Guard y repositorio deben compartir la UoW; validar actor fuera del handler."""

    command_type: type[C]
    target: OrderStatus

    def __init__(
        self,
        *,
        orders: IOrderRepository,
        guard: OrderMutationGuard,
        policy: OrderTransitionPolicy,
        idempotency: IdempotencyStore,
    ) -> None:
        self._orders, self._guard, self._policy, self._idempotency = (
            orders,
            guard,
            policy,
            idempotency,
        )

    def handle(self, command: C, /) -> tuple[OrderStatusResult, Sequence[DomainEvent]]:
        if type(command) is not self.command_type or not all(
            (
                isinstance(command.tenant_id, TenantId),
                isinstance(command.business_id, BusinessId),
                isinstance(command.location_id, LocationId),
                isinstance(command.order_id, OrderId),
            )
        ):
            raise ApplicationError("Tipo de comando o ámbito inválido")
        key, digest, tid = _key(command), request_digest(command), command.tenant_id
        if not self._idempotency.reserve(tid, key, digest):
            cached = self._idempotency.get(tid, key)
            if (
                cached is not None
                and cached[0] == digest
                and isinstance(cached[1], OrderStatusResult)
            ):
                result = cached[1]
                if (
                    result.tenant_id,
                    result.business_id,
                    result.location_id,
                    result.order_id,
                    result.status,
                ) == (tid, command.business_id, command.location_id, command.order_id, self.target):
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
            updated = replace(order)
            if self.target in {OrderStatus.VALIDATED, OrderStatus.CONFIRMED} and (
                not updated.lines or updated.total is None
            ):
                raise ApplicationError("Se requieren líneas y total coherente")
            if self._policy.approve(order=replace(updated), target=self.target) is not True:
                raise ApplicationError("Política de transición no aprobada")
            updated.transition_to(self.target)
            self._orders.save(updated)
            result = OrderStatusResult(
                tenant_id=tid,
                business_id=command.business_id,
                location_id=command.location_id,
                order_id=command.order_id,
                status=self.target,
                total=updated.total,
            )
            return result, updated.domain_events
        except BaseException:
            try:
                self._idempotency.release(tid, key)
            except Exception:
                pass
            raise

    def build_hooks(
        self, input: C, result: OrderStatusResult, /
    ) -> ExecutionHooks[OrderStatusResult]:
        key, digest, tid = _key(input), request_digest(input), input.tenant_id

        def success(_result: OrderStatusResult) -> None:
            self._idempotency.complete(tid, key, digest, result)

        def failure(_exc: BaseException) -> None:
            self._idempotency.release(tid, key)

        return ExecutionHooks(on_success=success, on_failure=failure)


class ValidateOrderHandler(_Handler[ValidateOrder]):
    command_type = ValidateOrder
    target = OrderStatus.VALIDATED


class ConfirmOrderHandler(_Handler[ConfirmOrder]):
    command_type = ConfirmOrder
    target = OrderStatus.CONFIRMED


class ReturnOrderToDraftHandler(_Handler[ReturnOrderToDraft]):
    command_type = ReturnOrderToDraft
    target = OrderStatus.DRAFT


class CancelOrderHandler(_Handler[CancelOrder]):
    command_type = CancelOrder
    target = OrderStatus.CANCELLED


class PrepareOrderHandler(_Handler[PrepareOrder]):
    command_type = PrepareOrder
    target = OrderStatus.PREPARING


class MarkOrderReadyHandler(_Handler[MarkOrderReady]):
    command_type = MarkOrderReady
    target = OrderStatus.READY


class DispatchOrderHandler(_Handler[DispatchOrder]):
    command_type = DispatchOrder
    target = OrderStatus.DELIVERING


class CompleteOrderHandler(_Handler[CompleteOrder]):
    command_type = CompleteOrder
    target = OrderStatus.COMPLETED
