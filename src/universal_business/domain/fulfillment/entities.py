"""Aggregado mínimo Fulfillment (skeleton 0.1)."""

from __future__ import annotations

from dataclasses import dataclass

from universal_business.domain.fulfillment.value_objects import FulfillmentStatus, FulfillmentType
from universal_business.domain.shared.base import BaseEntity
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    FulfillmentId,
    LocationId,
    OrderId,
    TenantId,
)


@dataclass(kw_only=True)
class Fulfillment(BaseEntity[FulfillmentId]):
    """Cumplimiento de un Order (entrega, retiro, envío, etc.)."""

    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId  # OBLIGATORIO
    order_id: OrderId
    type: FulfillmentType
    status: FulfillmentStatus = FulfillmentStatus.PENDING
    notes: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.type, FulfillmentType):
            raise InvariantViolationError("Fulfillment.type debe ser FulfillmentType")
        if not isinstance(self.status, FulfillmentStatus):
            raise InvariantViolationError("Fulfillment.status debe ser FulfillmentStatus")


__all__ = ["Fulfillment"]
