"""Añadir una línea con idempotencia y protección transaccional."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from universal_business.application.errors import ApplicationError, IdempotencyConflictError
from universal_business.application.execution import ExecutionHooks, IdempotentReplay
from universal_business.application.idempotency import (
    IdempotencyKey,
    IdempotencyStore,
    scoped_idempotency_key,
)
from universal_business.application.orders.commands import AddOrderLine
from universal_business.application.request_digest import request_digest
from universal_business.domain.catalog.entities import Offering
from universal_business.domain.catalog.ports import IOfferingRepository
from universal_business.domain.orders.entities import Order
from universal_business.domain.orders.events import OrderLineAdded
from universal_business.domain.orders.line import OrderLine
from universal_business.domain.orders.mutation import OrderMutationGuard
from universal_business.domain.orders.offering_snapshot import capture_offering_line
from universal_business.domain.orders.ports import IOrderRepository
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    OfferingId,
    OrderId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money


class OrderLinePolicy(Protocol):
    """Autorizar importes y evaluar política de impuestos; sin implementación por defecto.

    No sustituye la autorización del actor en la frontera antes de llamar al
    handler, incluidos replays. El adaptador debe rechazar si no puede decidir.
    Recibe copias superficiales: no debe mutar valores anidados en metadata.
    """

    def approve(self, *, order: Order, offering: Offering, line: OrderLine) -> bool: ...


@dataclass(frozen=True, kw_only=True)
class OrderLineResult:
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    order_id: OrderId
    offering_id: OfferingId
    line_id: UUID
    total: Money


def _key(command: AddOrderLine) -> IdempotencyKey:
    if not isinstance(command.idempotency_key, IdempotencyKey):
        raise ApplicationError("Se requiere una clave de idempotencia válida")
    return scoped_idempotency_key(
        business_id=command.business_id,
        operation=f"{type(command).__module__}.{type(command).__qualname__}",
        key=command.idempotency_key,
    )


class AddOrderLineHandler:
    """Ejecutar dentro de execute_use_case con puertos en una misma UoW.

    El guard protege todas las mutaciones del pedido hasta commit/rollback.
    El adaptador de catálogo debe ofrecer una lectura consistente con su
    política de actualización; el guard de pedidos no protege el catálogo.
    """

    def __init__(
        self,
        *,
        orders: IOrderRepository,
        offerings: IOfferingRepository,
        guard: OrderMutationGuard,
        policy: OrderLinePolicy,
        idempotency: IdempotencyStore,
    ) -> None:
        self._orders, self._offerings, self._guard = orders, offerings, guard
        self._policy, self._idempotency = policy, idempotency

    def handle(self, command: AddOrderLine, /) -> tuple[OrderLineResult, Sequence[DomainEvent]]:
        if not all(
            (
                isinstance(command.tenant_id, TenantId),
                isinstance(command.business_id, BusinessId),
                isinstance(command.location_id, LocationId),
                isinstance(command.order_id, OrderId),
                isinstance(command.offering_id, OfferingId),
                isinstance(command.line_id, UUID),
                isinstance(command.quantity, Decimal),
                isinstance(command.discount, Money),
                isinstance(command.tax, Money),
            )
        ):
            raise ApplicationError("Datos de línea o ámbito inválidos")
        key, digest, tid = _key(command), request_digest(command), command.tenant_id
        if not self._idempotency.reserve(tid, key, digest):
            cached = self._idempotency.get(tid, key)
            if (
                cached is not None
                and cached[0] == digest
                and isinstance(cached[1], OrderLineResult)
            ):
                result = cached[1]
                if (
                    result.tenant_id,
                    result.business_id,
                    result.location_id,
                    result.order_id,
                    result.offering_id,
                    result.line_id,
                ) == (
                    tid,
                    command.business_id,
                    command.location_id,
                    command.order_id,
                    command.offering_id,
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
            offering = self._offerings.get(
                tenant_id=tid, business_id=command.business_id, offering_id=command.offering_id
            )
            if offering is None or offering.id != command.offering_id:
                raise ApplicationError("Offering no encontrado o fuera del ámbito")
            line = capture_offering_line(
                tenant_id=tid,
                business_id=command.business_id,
                location_id=command.location_id,
                offering=offering,
                line_id=command.line_id,
                quantity=command.quantity,
                discount=command.discount,
                tax=command.tax,
            )
            if (
                self._policy.approve(order=replace(order), offering=replace(offering), line=line)
                is not True
            ):
                raise ApplicationError("Política de línea no aprobada")
            updated = replace(order)
            updated.add_line(line)
            if updated.total is None:
                raise ApplicationError("Total de pedido ausente")
            self._orders.save(updated)
            result = OrderLineResult(
                tenant_id=tid,
                business_id=command.business_id,
                location_id=command.location_id,
                order_id=command.order_id,
                offering_id=command.offering_id,
                line_id=command.line_id,
                total=updated.total,
            )
            event = OrderLineAdded(
                aggregate_id=command.order_id,
                tenant_id=tid,
                business_id=command.business_id,
                location_id=command.location_id,
                offering_id=command.offering_id,
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
        self, input: AddOrderLine, result: OrderLineResult, /
    ) -> ExecutionHooks[OrderLineResult]:
        key, digest, tid = _key(input), request_digest(input), input.tenant_id

        def success(_result: OrderLineResult) -> None:
            self._idempotency.complete(tid, key, digest, result)

        def failure(_exc: BaseException) -> None:
            self._idempotency.release(tid, key)

        return ExecutionHooks(on_success=success, on_failure=failure)
