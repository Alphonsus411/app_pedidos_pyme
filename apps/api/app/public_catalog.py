"""Lectura pública de catálogo con ámbito resuelto por el servidor."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass
from typing import Protocol

from universal_business.application.catalog import ListActiveOfferings, ListActiveOfferingsHandler
from universal_business.domain.shared.value_objects.ids import BusinessId, LocationId, TenantId
from universal_business.infrastructure.sqlite_offerings import SqliteOfferingRepository
from universal_business.infrastructure.sqlite_schema import initialize_sqlite_schema


class PublicCatalogUnavailable(LookupError):
    """El slug público no está configurado por el servidor."""


@dataclass(frozen=True)
class PublicCatalogScope:
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId


class PublicCatalogReader(Protocol):
    def list_active(self, *, business_slug: str, location_slug: str) -> list[dict[str, object]]: ...


class SqlitePublicCatalog:
    """Adaptador de lectura sin aceptar ámbito interno desde el navegador."""

    def __init__(
        self,
        *,
        connect: Callable[[], sqlite3.Connection],
        scopes: Mapping[tuple[str, str], PublicCatalogScope],
    ) -> None:
        self._connect = connect
        self._scopes = dict(scopes)

    def list_active(self, *, business_slug: str, location_slug: str) -> list[dict[str, object]]:
        scope = self._scopes.get((business_slug, location_slug))
        if scope is None:
            raise PublicCatalogUnavailable
        with closing(self._connect()) as connection:
            initialize_sqlite_schema(connection)
            offerings = ListActiveOfferingsHandler(
                offering_repository=SqliteOfferingRepository(connection)
            ).handle(
                ListActiveOfferings(
                    tenant_id=scope.tenant_id,
                    business_id=scope.business_id,
                    location_id=scope.location_id,
                )
            )
        return [
            {
                "id": str(offering.id),
                "name": offering.name,
                "description": offering.description,
                "price": None
                if offering.base_price is None
                else {
                    "amount": str(offering.base_price.amount),
                    "currency": str(offering.base_price.currency),
                },
            }
            for offering in sorted(offerings, key=lambda item: (item.name, str(item.id)))
        ]
