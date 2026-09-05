"""Value objects de Orders (estados propios del dominio)."""

from __future__ import annotations

from enum import StrEnum


class OrderStatus(StrEnum):
    DRAFT = "draft"
    VALIDATED = "validated"
    CONFIRMED = "confirmed"
    PREPARING = "preparing"
    READY = "ready"
    DELIVERING = "delivering"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class OrderChannel(StrEnum):
    COUNTER = "counter"
    PHONE = "phone"
    WHATSAPP = "whatsapp"
    WEB = "web"
    APP = "app"
    MARKETPLACE = "marketplace"
    OTHER = "other"


__all__ = ["OrderStatus", "OrderChannel"]
