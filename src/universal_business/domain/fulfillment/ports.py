"""Puertos repositorio para Fulfillment."""

from __future__ import annotations

from typing import Protocol

from universal_business.domain.fulfillment.entities import Fulfillment
from universal_business.domain.fulfillment.value_objects import FulfillmentStatus
from universal_business.domain.shared.value_objects.ids import (
    FulfillmentId,
    LocationId,
    OrderId,
    TenantId,
)


class IFulfillmentRepository(Protocol):
    def get(self, fulfillment_id: FulfillmentId) -> Fulfillment | None: ...
    def save(self, fulfillment: Fulfillment) -> None: ...

    def list_by_order(
        self,
        *,
        tenant_id: TenantId,
        order_id: OrderId,
        status: FulfillmentStatus | None = None,
    ) -> list[Fulfillment]: ...

    def list_by_location(
        self,
        *,
        tenant_id: TenantId,
        location_id: LocationId,
        status: FulfillmentStatus | None = None,
    ) -> list[Fulfillment]: ...


__all__ = ["IFulfillmentRepository"]
