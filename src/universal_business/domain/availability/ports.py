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
