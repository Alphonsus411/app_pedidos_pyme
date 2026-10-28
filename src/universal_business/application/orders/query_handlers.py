"""Lectura de pedidos con ámbito explícito y resultado inmutable."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from universal_business.application.errors import ApplicationError
from universal_business.application.orders.queries import GetOrder
from universal_business.domain.orders.line import OrderLine
from universal_business.domain.orders.ports import IOrderRepository
from universal_business.domain.orders.value_objects import OrderChannel, OrderStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CustomerId,
    LocationId,
    OrderId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money


@dataclass(frozen=True, kw_only=True)
class OrderView:
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    order_id: OrderId
    customer_id: CustomerId | None
    status: OrderStatus
    channel: OrderChannel
    lines: tuple[OrderLine, ...]
    total: Money | None
    external_ref: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class GetOrderHandler:
    """Consulta informativa: autorización del actor y lectura consistente son externas.

    El repositorio debe aislar tenant y devolver un estado coherente; no hay
    garantía de snapshot transaccional ni autorización por conocer IDs. El
    handler no distingue públicamente ausencia de datos fuera del ámbito.
    """

    def __init__(self, *, orders: IOrderRepository) -> None:
        self._orders = orders

    def handle(self, query: GetOrder, /) -> OrderView | None:
        if not all(
            (
                isinstance(query.tenant_id, TenantId),
                isinstance(query.business_id, BusinessId),
                isinstance(query.location_id, LocationId),
                isinstance(query.order_id, OrderId),
            )
        ):
            raise ApplicationError("Ámbito o identificador de pedido inválido")
        order = self._orders.get(tenant_id=query.tenant_id, order_id=query.order_id)
        if order is None or (order.tenant_id, order.business_id, order.location_id, order.id) != (
            query.tenant_id,
            query.business_id,
            query.location_id,
            query.order_id,
        ):
            return None
        if not isinstance(order.lines, tuple) or not all(
            isinstance(line, OrderLine) for line in order.lines
        ):
            raise ApplicationError("Líneas de pedido inválidas")
        return OrderView(
            tenant_id=order.tenant_id,
            business_id=order.business_id,
            location_id=order.location_id,
            order_id=order.id,
            customer_id=order.customer_id,
            status=order.status,
            channel=order.channel,
            lines=order.lines,
            total=order.total,
            external_ref=order.external_ref,
            notes=order.notes,
            created_at=order.created_at,
            updated_at=order.updated_at,
        )
