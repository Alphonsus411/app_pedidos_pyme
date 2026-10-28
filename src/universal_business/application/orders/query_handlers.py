"""Lectura de pedidos con ámbito explícito y resultado inmutable."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from universal_business.application.errors import ApplicationError
from universal_business.application.orders.queries import GetOrder, ListOrdersByLocation
from universal_business.domain.orders.entities import Order
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
        return _view(order)


def _view(order: Order) -> OrderView:
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


class ListOrdersByLocationHandler:
    """Listado limitado, sin orden ni paginación garantizados.

    El actor debe estar autorizado en la frontera. El adaptador debe devolver
    solo resultados del ámbito/filtro solicitado, con un máximo de limit y
    lectura coherente. No garantiza completitud ni snapshot transaccional.
    Los datos inconsistentes provocan fallo de toda la respuesta.
    """

    def __init__(self, *, orders: IOrderRepository) -> None:
        self._orders = orders

    def handle(self, query: ListOrdersByLocation, /) -> tuple[OrderView, ...]:
        if not all(
            (
                isinstance(query.tenant_id, TenantId),
                isinstance(query.business_id, BusinessId),
                isinstance(query.location_id, LocationId),
            )
        ):
            raise ApplicationError("Ámbito inválido")
        if query.status is not None and not isinstance(query.status, OrderStatus):
            raise ApplicationError("Filtro de estado inválido")
        if type(query.limit) is not int or not 1 <= query.limit <= 100:
            raise ApplicationError("El límite debe ser un entero entre 1 y 100")
        rows = self._orders.list_by_location(
            tenant_id=query.tenant_id,
            location_id=query.location_id,
            status=query.status,
            limit=query.limit,
        )
        if len(rows) > query.limit:
            raise ApplicationError("El repositorio devolvió más pedidos que el límite")
        seen: set[OrderId] = set()
        views: list[OrderView] = []
        for order in rows:
            if not isinstance(order, Order) or not isinstance(order.id, OrderId):
                raise ApplicationError("Pedido inválido devuelto por repositorio")
            if (order.tenant_id, order.business_id, order.location_id) != (
                query.tenant_id,
                query.business_id,
                query.location_id,
            ):
                raise ApplicationError("Repositorio devolvió pedido fuera del ámbito")
            if not isinstance(order.status, OrderStatus) or (
                query.status is not None and order.status != query.status
            ):
                raise ApplicationError("Repositorio devolvió estado incorrecto")
            if order.id in seen:
                raise ApplicationError("Repositorio devolvió pedidos duplicados")
            seen.add(order.id)
            views.append(_view(order))
        return tuple(views)
