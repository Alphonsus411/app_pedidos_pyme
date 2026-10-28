"""Eventos del ciclo de vida de pedidos."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from universal_business.domain.orders.value_objects import OrderStatus
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    OfferingId,
    OrderId,
    TenantId,
)


@dataclass(frozen=True, kw_only=True)
class OrderCreated(DomainEvent):
    """Creación de un borrador sin líneas."""

    aggregate_id: OrderId
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    aggregate_type: str = "Order"


@dataclass(frozen=True, kw_only=True)
class OrderLineAdded(DomainEvent):
    aggregate_id: OrderId
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    offering_id: OfferingId
    line_id: UUID
    aggregate_type: str = "Order"


@dataclass(frozen=True, kw_only=True)
class OrderLineRemoved(DomainEvent):
    aggregate_id: OrderId
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    offering_id: OfferingId
    line_id: UUID
    aggregate_type: str = "Order"


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
