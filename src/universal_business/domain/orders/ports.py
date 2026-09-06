"""Puertos repositorio para Orders (Hardening Gate 0.1-RC1).

Order está ligada a Location → Business → Tenant.
"""

from __future__ import annotations

from typing import Protocol

from universal_business.domain.orders.entities import Order
from universal_business.domain.orders.value_objects import OrderStatus
from universal_business.domain.shared.value_objects.ids import (
    CustomerId,
    LocationId,
    OrderId,
    TenantId,
)


class IOrderRepository(Protocol):
    def get(
        self,
        *,
        tenant_id: TenantId,
        order_id: OrderId,
    ) -> Order | None: ...
    def save(self, order: Order) -> None: ...

    def list_by_location(
        self,
        *,
        tenant_id: TenantId,
        location_id: LocationId,
        status: OrderStatus | None = None,
        limit: int = 50,
    ) -> list[Order]: ...

    def list_by_customer(
        self,
        *,
        tenant_id: TenantId,
        customer_id: CustomerId,
        status: OrderStatus | None = None,
    ) -> list[Order]: ...


__all__ = ["IOrderRepository"]
