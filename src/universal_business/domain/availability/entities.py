"""Aggregados mínimos AvailabilityRule y Block (skeleton Entrega 0.1).

Sin motor de disponibilidad aún — viene en FASE 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from universal_business.domain.availability.value_objects import AvailabilityStatus, BlockReason
from universal_business.domain.shared.base import BaseEntity
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import (
    AvailabilityBlockId,
    AvailabilityRuleId,
    LocationId,
    ResourceId,
    TenantId,
)
from universal_business.domain.shared.value_objects.temporal import DateRange, TimeRange


@dataclass(kw_only=True)
class AvailabilityRule(BaseEntity[AvailabilityRuleId]):
    """Regla de disponibilidad. Se aplica a Location, ResourceType o Resource concreto."""

    tenant_id: TenantId
    location_id: LocationId
    effective_range: DateRange
    status: AvailabilityStatus = AvailabilityStatus.ACTIVE
    resource_id: ResourceId | None = None
    capacity: int | None = None
    time_ranges: list[TimeRange] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.effective_range, DateRange):
            raise InvariantViolationError("AvailabilityRule.effective_range debe ser DateRange")
        for i, tr in enumerate(self.time_ranges):
            if not isinstance(tr, TimeRange):
                raise InvariantViolationError(
                    f"AvailabilityRule.time_ranges[{i}] no es TimeRange: {tr!r}"
                )
        if self.capacity is not None and self.capacity < 0:
            raise InvariantViolationError("AvailabilityRule.capacity no puede ser negativo")


@dataclass(kw_only=True)
class AvailabilityBlock(BaseEntity[AvailabilityBlockId]):
    """Bloque / excepción: cierre total, feriado, mantenimiento."""

    tenant_id: TenantId
    location_id: LocationId
    reason: BlockReason
    blocked_range: DateRange
    status: AvailabilityStatus = AvailabilityStatus.ACTIVE
    resource_id: ResourceId | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.reason, BlockReason):
            raise InvariantViolationError("AvailabilityBlock.reason debe ser BlockReason")
        if not isinstance(self.blocked_range, DateRange):
            raise InvariantViolationError("AvailabilityBlock.blocked_range debe ser DateRange")


__all__ = [
    "AvailabilityRule",
    "AvailabilityBlock",
    "AvailabilityRuleId",
    "AvailabilityBlockId",
]
