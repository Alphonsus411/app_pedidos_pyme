"""Módulo de dominio: Catálogo (skeleton mínimo)."""

from __future__ import annotations

from universal_business.domain.catalog.entities import (
    CatalogCategory,
    CatalogItem,
    Offering,
    OfferingResourceRequirement,
)
from universal_business.domain.catalog.events import (
    CatalogCategoryCreated,
    OfferingActivated,
    OfferingArchived,
    OfferingCreated,
    OfferingDeactivated,
    OfferingPriceChanged,
)
from universal_business.domain.catalog.ports import (
    ICatalogCategoryRepository,
    ICatalogRepository,
    IOfferingRepository,
)
from universal_business.domain.catalog.value_objects import (
    CatalogItemStatus,
    CatalogItemType,
)

__all__ = [
    "CatalogItem",
    "CatalogItemStatus",
    "CatalogItemType",
    "ICatalogRepository",
    "IOfferingRepository",
    "ICatalogCategoryRepository",
    "Offering",
    "CatalogCategory",
    "OfferingResourceRequirement",
    "OfferingCreated",
    "OfferingActivated",
    "OfferingDeactivated",
    "OfferingArchived",
    "OfferingPriceChanged",
    "CatalogCategoryCreated",
]
