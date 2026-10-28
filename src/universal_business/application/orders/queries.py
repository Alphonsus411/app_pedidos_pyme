"""Consultas de pedidos."""

from dataclasses import dataclass

from universal_business.application.messaging.queries import Query
from universal_business.domain.orders.value_objects import OrderStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    OrderId,
    TenantId,
)


@dataclass(frozen=True, kw_only=True)
class GetOrder(Query):
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    order_id: OrderId


@dataclass(frozen=True, kw_only=True)
class ListOrdersByLocation(Query):
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    status: OrderStatus | None = None
    limit: int = 50
