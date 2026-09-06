"""Módulo application/resources — Gate 0.3: Resources Commands/Queries/Handlers.

Exporta la API pública de la capa de aplicación para el módulo de recursos.
"""

from __future__ import annotations

from universal_business.application.resources.commands import (
    ActivateResource,
    ArchiveResource,
    AssignResourceToLocation,
    CreateResource,
    CreateResourceType,
    DeactivateResource,
)
from universal_business.application.resources.handlers import (
    ActivateResourceHandler,
    ArchiveResourceHandler,
    AssignResourceToLocationHandler,
    CreateResourceHandler,
    CreateResourceTypeHandler,
    DeactivateResourceHandler,
    GetResourceHandler,
    ListActiveResourcesHandler,
    ListResourceTypesByBusinessHandler,
    ListResourcesByBusinessHandler,
    ListResourcesByLocationHandler,
)
from universal_business.application.resources.queries import (
    GetResource,
    ListActiveResources,
    ListResourceTypesByBusiness,
    ListResourcesByBusiness,
    ListResourcesByLocation,
)

__all__ = [
    # Commands
    "CreateResourceType",
    "CreateResource",
    "ActivateResource",
    "DeactivateResource",
    "ArchiveResource",
    "AssignResourceToLocation",
    # Queries
    "GetResource",
    "ListResourcesByBusiness",
    "ListResourcesByLocation",
    "ListActiveResources",
    "ListResourceTypesByBusiness",
    # Handlers
    "CreateResourceTypeHandler",
    "CreateResourceHandler",
    "ActivateResourceHandler",
    "DeactivateResourceHandler",
    "ArchiveResourceHandler",
    "AssignResourceToLocationHandler",
    "GetResourceHandler",
    "ListResourcesByBusinessHandler",
    "ListResourcesByLocationHandler",
    "ListActiveResourcesHandler",
    "ListResourceTypesByBusinessHandler",
]
