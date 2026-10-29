"""Repositorio SQLite de ubicaciones para el prototipo."""

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from typing import Any

from universal_business.domain.business.entities import Location
from universal_business.domain.business.value_objects import (
    WEEKDAYS,
    Address,
    ContactInfo,
    LocationStatus,
    OperatingHours,
)
from universal_business.domain.shared.value_objects.ids import BusinessId, LocationId, TenantId
from universal_business.domain.shared.value_objects.temporal import TimeRange


def create_sqlite_locations_schema(connection: sqlite3.Connection) -> None:
    """Crear el esquema inicial; no realiza migraciones de tablas existentes."""
    connection.execute("""CREATE TABLE IF NOT EXISTS locations (
        tenant_id TEXT NOT NULL, id TEXT NOT NULL, business_id TEXT NOT NULL,
        name TEXT NOT NULL, timezone TEXT NOT NULL, status TEXT NOT NULL,
        payload TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        PRIMARY KEY (tenant_id, id)
    )""")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS locations_scope ON locations (tenant_id, business_id, status)"
    )


def _payload(location: Location) -> str:
    if (
        type(location) is not Location
        or type(location.address) is not Address
        or type(location.operating_hours) is not OperatingHours
        or (location.contact_info is not None and type(location.contact_info) is not ContactInfo)
    ):
        raise ValueError("Subtipo de ubicación no soportado")
    hours: dict[str, list[dict[str, str]]] = {}
    if set(location.operating_hours.by_day) != set(WEEKDAYS):
        raise ValueError("Días del horario inválidos")
    for day, slots in location.operating_hours.by_day.items():
        if any(type(slot) is not TimeRange for slot in slots):
            raise ValueError("Subtipo de intervalo no soportado")
        hours[day] = [
            {"start": slot.start.isoformat(), "end": slot.end.isoformat()} for slot in slots
        ]
    return json.dumps(
        {
            "version": 1,
            "address": asdict(location.address),
            "hours": hours,
            "contact": asdict(location.contact_info) if location.contact_info else None,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _from_row(row: tuple[Any, ...]) -> Location:
    payload = json.loads(row[6])
    if (
        type(payload) is not dict
        or type(payload.get("version")) is not int
        or payload["version"] != 1
        or set(payload) != {"version", "address", "hours", "contact"}
    ):
        raise ValueError("Formato de ubicación inválido")
    if type(payload["hours"]) is not dict or set(payload["hours"]) != set(WEEKDAYS):
        raise ValueError("Días del horario inválidos")
    hours: Any = {
        day: [
            TimeRange(datetime.fromisoformat(slot["start"]), datetime.fromisoformat(slot["end"]))
            for slot in slots
        ]
        for day, slots in payload["hours"].items()
    }
    return Location(
        tenant_id=TenantId.from_raw(row[0]),
        id=LocationId.from_raw(row[1]),
        business_id=BusinessId.from_raw(row[2]),
        name=row[3],
        timezone=row[4],
        status=LocationStatus(row[5]),
        address=Address(**payload["address"]),
        operating_hours=OperatingHours(by_day=hours),
        contact_info=ContactInfo(**payload["contact"]) if payload["contact"] is not None else None,
        created_at=datetime.fromisoformat(row[7]),
        updated_at=datetime.fromisoformat(row[8]),
    )


class SqliteLocationRepository:
    """Consulta por tenant/business; escritura requiere transacción activa.

    El nombre de zona de la ubicación se conserva; los instantes del horario
    conservan su offset, pero no el nombre IANA del tzinfo de cada intervalo.
    No valida autorización ni existencia del negocio asociado.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(
        self, *, tenant_id: TenantId, business_id: BusinessId, location_id: LocationId
    ) -> Location | None:
        row = self._connection.execute(
            "SELECT * FROM locations WHERE tenant_id=? AND business_id=? AND id=?",
            (str(tenant_id), str(business_id), str(location_id)),
        ).fetchone()
        return _from_row(row) if row else None

    def save(self, location: Location) -> None:
        if not self._connection.in_transaction:
            raise RuntimeError("La escritura requiere una transacción activa")
        values = (
            str(location.tenant_id),
            str(location.id),
            str(location.business_id),
            location.name,
            location.timezone,
            location.status.value,
            _payload(location),
            location.created_at.isoformat(),
            location.updated_at.isoformat(),
        )
        result = self._connection.execute(
            """INSERT INTO locations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id,id) DO UPDATE SET name=excluded.name, timezone=excluded.timezone,
            status=excluded.status, payload=excluded.payload, updated_at=excluded.updated_at
            WHERE locations.business_id=excluded.business_id AND locations.created_at=excluded.created_at""",
            values,
        )
        if result.rowcount != 1:
            raise ValueError("No se puede cambiar el negocio o fecha de creación de la ubicación")

    def list_by_business(
        self, *, tenant_id: TenantId, business_id: BusinessId, status: LocationStatus | None = None
    ) -> list[Location]:
        sql = "SELECT * FROM locations WHERE tenant_id=? AND business_id=?"
        params: list[object] = [str(tenant_id), str(business_id)]
        if status is not None:
            sql += " AND status=?"
            params.append(status.value)
        return [_from_row(row) for row in self._connection.execute(sql, params).fetchall()]
