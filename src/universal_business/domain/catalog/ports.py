"""Puertos repositorio para Catalog."""

from __future__ import annotations

from typing import Protocol

from universal_business.domain.catalog.entities import CatalogItem
from universal_business.domain.catalog.value_objects import CatalogItemStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CatalogItemId,
    LocationId,
    TenantId,
)


class ICatalogRepository(Protocol):
    def get(self, item_id: CatalogItemId) -> CatalogItem | None: ...
    def save(self, item: CatalogItem) -> None: ...
    def list_by_business(
        self,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId | None = None,
        status: CatalogItemStatus | None = None,
    ) -> list[CatalogItem]: ...


__all__ = ["ICatalogRepository"]
