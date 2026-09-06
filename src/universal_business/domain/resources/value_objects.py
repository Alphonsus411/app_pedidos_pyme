"""Value objects de Resources."""

from __future__ import annotations

from enum import StrEnum


class ResourceType(StrEnum):
    TABLE = "table"
    ROOM = "room"
    STAFF = "staff"
    EQUIPMENT = "equipment"
    SLOT = "slot"
    OTHER = "other"


class ResourceStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    MAINTENANCE = "maintenance"
    RETIRED = "retired"
    ARCHIVED = "archived"


__all__ = ["ResourceType", "ResourceStatus"]
