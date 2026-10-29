"""Persistencia SQLite de ofertas; esquema independiente del inicializador v2."""

import json
import sqlite3
from datetime import datetime
from decimal import Context, Decimal, localcontext
from typing import Any

from universal_business.application.events.reservation_codec import _unique_object, _validate_json
from universal_business.domain.catalog.entities import Offering
from universal_business.domain.catalog.value_objects import CatalogItemStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CatalogCategoryId,
    LocationId,
    OfferingId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money


def create_sqlite_offerings_schema(connection: sqlite3.Connection) -> None:
    """Crear esquema explícito; no migra bases ni cambia user_version."""
    connection.execute("""CREATE TABLE IF NOT EXISTS offerings (
        tenant_id TEXT NOT NULL, id TEXT NOT NULL, business_id TEXT NOT NULL,
        name TEXT NOT NULL, description TEXT, status TEXT NOT NULL, category_id TEXT,
        payload TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        PRIMARY KEY (tenant_id, id)
    )""")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS offerings_scope ON offerings (tenant_id, business_id, status)"
    )


def _encode(offering: Offering) -> str:
    if type(offering) is not Offering or any(
        type(x) is not LocationId for x in offering.location_ids
    ):
        raise ValueError("Tipo de oferta o ubicación no soportado")
    metadata = dict(offering.metadata)
    _validate_json(metadata)
    price = offering.base_price
    if price is not None and (type(price) is not Money or not price.amount.is_finite()):
        raise ValueError("Precio inválido")
    payload = {
        "version": 1,
        "locations": sorted(str(x) for x in offering.location_ids),
        "metadata": metadata,
        "price": None
        if price is None
        else {"amount": str(price.amount), "currency": str(price.currency)},
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _decode(row: tuple[Any, ...]) -> Offering:
    payload = json.loads(row[7], object_pairs_hook=_unique_object)
    if (
        type(payload) is not dict
        or set(payload) != {"version", "locations", "metadata", "price"}
        or type(payload["version"]) is not int
        or payload["version"] != 1
        or type(payload["locations"]) is not list
        or type(payload["metadata"]) is not dict
        or any(type(x) is not str for x in payload["locations"])
    ):
        raise ValueError("Oferta SQLite inválida")
    _validate_json(payload["metadata"])
    locations = [LocationId.from_raw(x) for x in payload["locations"]]
    if len(set(locations)) != len(locations):
        raise ValueError("Ubicaciones duplicadas")
    raw = payload["price"]
    price = None
    if raw is not None:
        if (
            type(raw) is not dict
            or set(raw) != {"amount", "currency"}
            or any(type(raw[x]) is not str for x in raw)
        ):
            raise ValueError("Precio inválido")
        amount = Decimal(raw["amount"])
        with localcontext(Context(prec=50)):
            price = Money(amount, raw["currency"])
        if not price.amount.is_finite() or price.amount != amount:
            raise ValueError("Precio inválido")
    offering = Offering(
        tenant_id=TenantId.from_raw(row[0]),
        id=OfferingId.from_raw(row[1]),
        business_id=BusinessId.from_raw(row[2]),
        name=row[3],
        description=row[4],
        status=CatalogItemStatus(row[5]),
        category_id=CatalogCategoryId.from_raw(row[6]) if row[6] else None,
        base_price=price,
        location_ids=frozenset(locations),
        metadata=payload["metadata"],
        created_at=datetime.fromisoformat(row[8]),
        updated_at=datetime.fromisoformat(row[9]),
    )
    offering.clear_domain_events()
    return offering


class SqliteOfferingRepository:
    """Las escrituras exigen transacción; el caller controla BEGIN IMMEDIATE.

    Una oferta sin ubicaciones aplica a todo el negocio. No valida autorización,
    referencias ni garantiza protección si otras escrituras eluden la UoW.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(
        self, /, *, tenant_id: TenantId, business_id: BusinessId, offering_id: OfferingId
    ) -> Offering | None:
        row = self._connection.execute(
            "SELECT * FROM offerings WHERE tenant_id=? AND business_id=? AND id=?",
            (str(tenant_id), str(business_id), str(offering_id)),
        ).fetchone()
        return _decode(row) if row else None

    def save(self, offering: Offering, /) -> None:
        if not self._connection.in_transaction:
            raise RuntimeError("La escritura requiere una transacción activa")
        result = self._connection.execute(
            """INSERT INTO offerings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id,id) DO UPDATE SET name=excluded.name, description=excluded.description,
            status=excluded.status, category_id=excluded.category_id, payload=excluded.payload, updated_at=excluded.updated_at
            WHERE offerings.business_id=excluded.business_id AND offerings.created_at=excluded.created_at""",
            (
                str(offering.tenant_id),
                str(offering.id),
                str(offering.business_id),
                offering.name,
                offering.description,
                offering.status.value,
                str(offering.category_id) if offering.category_id else None,
                _encode(offering),
                offering.created_at.isoformat(),
                offering.updated_at.isoformat(),
            ),
        )
        if result.rowcount != 1:
            raise ValueError("No se puede cambiar el negocio o fecha de creación")

    def list_by_business(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId | None = None,
        status: CatalogItemStatus | None = None,
    ) -> list[Offering]:
        if status is not None and not isinstance(status, CatalogItemStatus):
            raise ValueError("Estado inválido")
        sql = "SELECT * FROM offerings WHERE tenant_id=? AND business_id=?"
        params: list[object] = [str(tenant_id), str(business_id)]
        if status is not None:
            sql += " AND status=?"
            params.append(status.value)
        items = [_decode(row) for row in self._connection.execute(sql, params).fetchall()]
        return [
            x
            for x in items
            if location_id is None or not x.location_ids or location_id in x.location_ids
        ]

    def list_active(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId | None = None,
    ) -> list[Offering]:
        return self.list_by_business(
            tenant_id=tenant_id,
            business_id=business_id,
            location_id=location_id,
            status=CatalogItemStatus.ACTIVE,
        )
