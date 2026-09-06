"""Value objects de Availability."""

from __future__ import annotations

from enum import StrEnum


class AvailabilityStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class BlockReason(StrEnum):
    HOLIDAY = "holiday"
    MAINTENANCE = "maintenance"
    PRIVATE_EVENT = "private_event"
    MANUAL = "manual"


__all__ = ["AvailabilityStatus", "BlockReason"]
