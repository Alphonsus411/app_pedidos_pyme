"""Repositorio SQLite de clientes para el prototipo."""

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from typing import Any

from universal_business.domain.business.value_objects import Address
from universal_business.domain.customers.entities import Customer
from universal_business.domain.customers.value_objects import (
    Consent,
    ContactPoint,
    CustomerPreferences,
    CustomerStatus,
)
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CustomerId,
    LocationId,
    TenantId,
)


def create_sqlite_customers_schema(connection: sqlite3.Connection) -> None:
    """Instalar esquema inicial sin migración automática de datos existentes."""
    connection.execute("""CREATE TABLE IF NOT EXISTS customers (
        tenant_id TEXT NOT NULL, id TEXT NOT NULL, business_id TEXT NOT NULL,
        location_id TEXT, external_ref TEXT, given_name TEXT NOT NULL, family_name TEXT,
        status TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        PRIMARY KEY (tenant_id, id), UNIQUE (tenant_id, business_id, external_ref)
    )""")


def _payload(customer: Customer) -> str:
    if (
        type(customer) is not Customer
        or type(customer.preferences) is not CustomerPreferences
        or any(type(value) is not ContactPoint for value in customer.contact_points)
        or any(type(value) is not Address for value in customer.addresses)
        or any(type(value) is not Consent for value in customer.consents)
    ):
        raise ValueError("Subtipos de cliente no soportados por el formato v1")
    contacts = []
    for contact in customer.contact_points:
        item = asdict(contact)
        item["verified_at"] = contact.verified_at.isoformat() if contact.verified_at else None
        contacts.append(item)
    consents = []
    for consent in customer.consents:
        item = asdict(consent)
        item["granted_at"] = consent.granted_at.isoformat()
        item["revoked_at"] = consent.revoked_at.isoformat() if consent.revoked_at else None
        consents.append(item)
    return json.dumps(
        {
            "version": 1,
            "contacts": contacts,
            "addresses": [asdict(addr) for addr in customer.addresses],
            "consents": consents,
            "preferences": asdict(customer.preferences),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _from_row(row: tuple[Any, ...]) -> Customer:
    data = json.loads(row[8])
    if type(data) is not dict or type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("Formato de cliente no soportado")
    if set(data) != {"version", "contacts", "addresses", "consents", "preferences"}:
        raise ValueError("Campos de cliente inválidos")
    contacts = []
    for item in data["contacts"]:
        fields = dict(item)
        if fields["verified_at"] is not None:
            fields["verified_at"] = datetime.fromisoformat(fields["verified_at"])
        contacts.append(ContactPoint(**fields))
    consents = []
    for item in data["consents"]:
        fields = dict(item)
        fields["granted_at"] = datetime.fromisoformat(fields["granted_at"])
        if fields["revoked_at"] is not None:
            fields["revoked_at"] = datetime.fromisoformat(fields["revoked_at"])
        consents.append(Consent(**fields))
    return Customer(
        tenant_id=TenantId.from_raw(row[0]),
        id=CustomerId.from_raw(row[1]),
        business_id=BusinessId.from_raw(row[2]),
        location_id=LocationId.from_raw(row[3]) if row[3] is not None else None,
        external_ref=row[4],
        given_name=row[5],
        family_name=row[6],
        status=CustomerStatus(row[7]),
        contact_points=contacts,
        addresses=[Address(**a) for a in data["addresses"]],
        consents=consents,
        preferences=CustomerPreferences(**data["preferences"]),
        created_at=datetime.fromisoformat(row[9]),
        updated_at=datetime.fromisoformat(row[10]),
    )


class SqliteCustomerRepository:
    """Alcance tenant/business explícito; escritura en transacción compartida.

    Los datetimes conservan instante y offset, no nombre de zona IANA. Search
    filtra ubicación exacta si se suministra y usa lower de SQLite (ASCII).
    No sustituye autorización, migraciones ni control de datos personales.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(
        self, *, tenant_id: TenantId, business_id: BusinessId, customer_id: CustomerId
    ) -> Customer | None:
        row = self._connection.execute(
            "SELECT * FROM customers WHERE tenant_id=? AND business_id=? AND id=?",
            (str(tenant_id), str(business_id), str(customer_id)),
        ).fetchone()
        return _from_row(row) if row else None

    def get_by_external_ref(
        self, *, tenant_id: TenantId, business_id: BusinessId, external_ref: str
    ) -> Customer | None:
        row = self._connection.execute(
            "SELECT * FROM customers WHERE tenant_id=? AND business_id=? AND external_ref=?",
            (str(tenant_id), str(business_id), external_ref),
        ).fetchone()
        return _from_row(row) if row else None

    def save(self, customer: Customer) -> None:
        if not self._connection.in_transaction:
            raise RuntimeError("La escritura requiere una transacción activa")
        values = (
            str(customer.tenant_id),
            str(customer.id),
            str(customer.business_id),
            str(customer.location_id) if customer.location_id else None,
            customer.external_ref,
            customer.given_name,
            customer.family_name,
            customer.status.value,
            _payload(customer),
            customer.created_at.isoformat(),
            customer.updated_at.isoformat(),
        )
        result = self._connection.execute(
            """INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id, id) DO UPDATE SET
            location_id=excluded.location_id, external_ref=excluded.external_ref,
            given_name=excluded.given_name, family_name=excluded.family_name,
            status=excluded.status, payload=excluded.payload, updated_at=excluded.updated_at
            WHERE customers.business_id=excluded.business_id AND customers.created_at=excluded.created_at""",
            values,
        )
        if result.rowcount != 1:
            raise ValueError("No se puede cambiar el negocio o la fecha de creación del cliente")

    def search(
        self,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId | None = None,
        query: str | None = None,
        status: CustomerStatus | None = None,
        limit: int = 50,
    ) -> list[Customer]:
        if type(limit) is not int or limit < 1:
            raise ValueError("El límite debe ser un entero positivo")
        sql = "SELECT * FROM customers WHERE tenant_id=? AND business_id=?"
        params: list[object] = [str(tenant_id), str(business_id)]
        if location_id is not None:
            sql += " AND location_id=?"
            params.append(str(location_id))
        if status is not None:
            sql += " AND status=?"
            params.append(status.value)
        if query is not None:
            sql += " AND instr(lower(given_name || ' ' || coalesce(family_name, '')), lower(?)) > 0"
            params.append(query)
        sql += " ORDER BY id LIMIT ?"
        params.append(limit)
        return [_from_row(row) for row in self._connection.execute(sql, params).fetchall()]
