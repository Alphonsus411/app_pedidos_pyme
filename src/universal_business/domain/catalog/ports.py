"""Puertos repositorio para Catalog (Hardening Gate 0.1-RC1).

CatalogItem pertenece a Tenant + Business; location_id es opcional (item de nivel business).
"""

from __future__ import annotations

from typing import Protocol

from universal_business.domain.catalog.entities import (
    CatalogCategory,
    CatalogItem,
    Offering,
)
from universal_business.domain.catalog.value_objects import CatalogItemStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CatalogCategoryId,
    CatalogItemId,
    LocationId,
    OfferingId,
    TenantId,
)


class ICatalogRepository(Protocol):
    def get(
        self,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        item_id: CatalogItemId,
    ) -> CatalogItem | None: ...
    def save(self, item: CatalogItem) -> None: ...
    def list_by_business(
        self,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId | None = None,
        status: CatalogItemStatus | None = None,
    ) -> list[CatalogItem]: ...


class IOfferingRepository(Protocol):
    def get(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        offering_id: OfferingId,
    ) -> Offering | None: ...
    def save(self, offering: Offering, /) -> None: ...
    def list_by_business(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId | None = None,
        status: CatalogItemStatus | None = None,
    ) -> list[Offering]: ...
    def list_active(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId | None = None,
    ) -> list[Offering]: ...


class ICatalogCategoryRepository(Protocol):
    def get(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        category_id: CatalogCategoryId,
    ) -> CatalogCategory | None: ...
    def save(self, category: CatalogCategory, /) -> None: ...
    def list_by_business(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        status: CatalogItemStatus | None = None,
        parent_category_id: CatalogCategoryId | None = None,
    ) -> list[CatalogCategory]: ...


__all__ = ["ICatalogRepository", "IOfferingRepository", "ICatalogCategoryRepository"]
