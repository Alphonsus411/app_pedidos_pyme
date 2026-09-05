"""Value objects de Catalog. Enumerados concretos; estados NO compartidos."""

from __future__ import annotations

from enum import StrEnum


class CatalogItemType(StrEnum):
    PRODUCT = "product"
    SERVICE = "service"
    BUNDLE = "bundle"
    DIGITAL = "digital"
    OTHER = "other"


class CatalogItemStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


__all__ = ["CatalogItemType", "CatalogItemStatus"]
