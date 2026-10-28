"""Puertos repositorio para Availability (FASE 1 implementa).

En 0.1 son Protocol skeleton con operaciones mínimas.
"""

from __future__ import annotations

from typing import Protocol

from universal_business.domain.availability.entities import AvailabilityBlock, AvailabilityRule
from universal_business.domain.shared.value_objects.ids import (
    LocationId,
    ResourceId,
    TenantId,
)
from universal_business.domain.shared.value_objects.temporal import DateRange


class IAvailabilityRepository(Protocol):
    """Read methods return complete candidates for the requested inclusive dates.

    list_rules_for_resource includes location-wide rules (resource_id=None)
    and rules for that resource; list_blocks includes both kinds of block.
    Neither method may silently truncate results. Caller validates tenant,
    location and resource scope and applies status and time filtering.
    """

    def save_rule(self, rule: AvailabilityRule) -> None: ...
    def save_block(self, block: AvailabilityBlock) -> None: ...

    def list_rules_for_resource(
        self,
        *,
        tenant_id: TenantId,
        location_id: LocationId,
        resource_id: ResourceId | None = None,
        range: DateRange,
    ) -> list[AvailabilityRule]: ...

    def list_blocks(
        self,
        *,
        tenant_id: TenantId,
        location_id: LocationId,
        range: DateRange,
    ) -> list[AvailabilityBlock]: ...


__all__ = ["IAvailabilityRepository"]
