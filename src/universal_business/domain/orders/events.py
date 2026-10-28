"""Eventos del ciclo de vida de pedidos."""

from __future__ import annotations

from dataclasses import dataclass

from universal_business.domain.orders.value_objects import OrderStatus
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    OrderId,
    TenantId,
)


@dataclass(frozen=True, kw_only=True)
class OrderStatusChanged(DomainEvent):
    """Cambio real de estado; su persistencia y publicación son externas."""

    aggregate_id: OrderId
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    previous_status: OrderStatus
    new_status: OrderStatus
    aggregate_type: str = "Order"
