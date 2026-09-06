"""Subpackage application.catalog (Gate 0.3 — Catalog Resources).

Reexporta públicamente todos los Commands, Queries y Handlers concretos del
módulo de Catálogo. También se exportan los submódulos individuales para
importaciones gránulares si el consumidor lo prefiere.
"""

from universal_business.application.catalog import (
    commands as commands,
)
from universal_business.application.catalog import (
    handlers as handlers,
)
from universal_business.application.catalog import (
    queries as queries,
)
from universal_business.application.catalog.commands import (
    ActivateOffering,
    ArchiveOffering,
    ChangeOfferingPrice,
    CreateCatalogCategory,
    CreateOffering,
    DeactivateOffering,
)
from universal_business.application.catalog.handlers import (
    ActivateOfferingHandler,
    ArchiveOfferingHandler,
    ChangeOfferingPriceHandler,
    CreateCatalogCategoryHandler,
    CreateOfferingHandler,
    DeactivateOfferingHandler,
    GetOfferingHandler,
    ListActiveOfferingsHandler,
    ListCategoriesByBusinessHandler,
    ListOfferingsByBusinessHandler,
    ListOfferingsByLocationHandler,
)
from universal_business.application.catalog.queries import (
    GetOffering,
    ListActiveOfferings,
    ListCategoriesByBusiness,
    ListOfferingsByBusiness,
    ListOfferingsByLocation,
)

__all__ = [
    # Submodules
    "commands",
    "queries",
    "handlers",
    # Commands
    "CreateOffering",
    "ActivateOffering",
    "DeactivateOffering",
    "ArchiveOffering",
    "ChangeOfferingPrice",
    "CreateCatalogCategory",
    # Queries
    "GetOffering",
    "ListOfferingsByBusiness",
    "ListOfferingsByLocation",
    "ListActiveOfferings",
    "ListCategoriesByBusiness",
    # Handlers
    "CreateOfferingHandler",
    "ActivateOfferingHandler",
    "DeactivateOfferingHandler",
    "ArchiveOfferingHandler",
    "ChangeOfferingPriceHandler",
    "CreateCatalogCategoryHandler",
    "GetOfferingHandler",
    "ListOfferingsByBusinessHandler",
    "ListOfferingsByLocationHandler",
    "ListActiveOfferingsHandler",
    "ListCategoriesByBusinessHandler",
]
