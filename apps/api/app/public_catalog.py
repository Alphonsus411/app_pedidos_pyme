"""Lectura pública de catálogo con ámbito resuelto por el servidor."""

from __future__ import annotations

import sqlite3
from base64 import b64decode, urlsafe_b64encode
from binascii import Error as BinasciiError
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass
from typing import Protocol

from universal_business.application.catalog import ListActiveOfferings, ListActiveOfferingsHandler
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    OfferingId,
    TenantId,
)
from universal_business.infrastructure.sqlite_offerings import SqliteOfferingRepository
from universal_business.infrastructure.sqlite_schema import initialize_sqlite_schema


class PublicCatalogUnavailable(LookupError):
    """El slug público no está configurado por el servidor."""


class PublicCatalogCursorInvalid(ValueError):
    """El cursor opaco no tiene el formato emitido por esta API."""


@dataclass(frozen=True)
class PublicCatalogScope:
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId


@dataclass(frozen=True)
class PublicCatalogPage:
    items: list[dict[str, object]]
    next_cursor: str | None


class PublicCatalogReader(Protocol):
    def list_active(
        self,
        *,
        business_slug: str,
        location_slug: str,
        limit: int,
        cursor: str | None,
    ) -> PublicCatalogPage: ...


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

    def list_active(
        self,
        *,
        business_slug: str,
        location_slug: str,
        limit: int,
        cursor: str | None,
    ) -> PublicCatalogPage:
        scope = self._scopes.get((business_slug, location_slug))
        if scope is None:
            raise PublicCatalogUnavailable
        if not 1 <= limit <= 100:
            raise ValueError("Catalog limit must be between 1 and 100")
        after = _decode_cursor(cursor) if cursor is not None else None
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
        sorted_offerings = sorted(offerings, key=lambda item: (item.name, str(item.id)))
        if after is not None:
            sorted_offerings = [
                item for item in sorted_offerings if (item.name, str(item.id)) > after
            ]
        page = sorted_offerings[:limit]
        return PublicCatalogPage(
            items=[
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
                for offering in page
            ],
            next_cursor=(
                _encode_cursor(name=page[-1].name, offering_id=str(page[-1].id))
                if len(sorted_offerings) > limit
                else None
            ),
        )


def _encode_cursor(*, name: str, offering_id: str) -> str:
    value = f"{name}\x00{offering_id}".encode()
    return urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = b64decode(cursor + padding, altchars=b"-_", validate=True).decode("utf-8")
        name, offering_id = raw.split("\x00", maxsplit=1)
        OfferingId.from_raw(offering_id)
    except (BinasciiError, InvariantViolationError, UnicodeDecodeError, ValueError) as exc:
        raise PublicCatalogCursorInvalid from exc
    if not name or not offering_id:
        raise PublicCatalogCursorInvalid
    return name, offering_id
