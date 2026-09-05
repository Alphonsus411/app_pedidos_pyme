"""Aggregado mínimo CatalogItem (Entrega 0.1 skeleton).

Nada de reglas de pricing ni stock — FASE 1 lo implementa.
"""

from __future__ import annotations

from dataclasses import dataclass

from universal_business.domain.catalog.value_objects import CatalogItemStatus, CatalogItemType
from universal_business.domain.shared.base import BaseEntity
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CatalogItemId,
    LocationId,
    TenantId,
)


@dataclass(kw_only=True)
class CatalogItem(BaseEntity[CatalogItemId]):
    """Ítem catálogo genérico (producto físico / servicio / combo / digital)."""

    tenant_id: TenantId
    business_id: BusinessId
    name: str
    type: CatalogItemType
    status: CatalogItemStatus = CatalogItemStatus.DRAFT
    location_id: LocationId | None = None  # OPCIONAL: catálogo por business entero si None
    sku: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.name, str) or not self.name.strip():
            raise InvariantViolationError("CatalogItem.name no puede ser vacío")
        object.__setattr__(self, "name", self.name.strip())
        if not isinstance(self.type, CatalogItemType):
            raise InvariantViolationError("CatalogItem.type debe ser CatalogItemType")
        if not isinstance(self.status, CatalogItemStatus):
            raise InvariantViolationError("CatalogItem.status debe ser CatalogItemStatus")


__all__ = ["CatalogItem"]
