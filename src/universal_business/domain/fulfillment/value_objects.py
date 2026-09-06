"""Value objects de Fulfillment (estados propios)."""

from __future__ import annotations

from enum import StrEnum


class FulfillmentStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETURNED = "returned"


class FulfillmentType(StrEnum):
    PICKUP = "pickup"
    DELIVERY = "delivery"
    DINING = "dining"
    SHIPPING = "shipping"
    OTHER = "other"


__all__ = ["FulfillmentStatus", "FulfillmentType"]
