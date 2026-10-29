"""Reglas y bloqueos SQLite para el prototipo de reservas."""

import json
import sqlite3
from datetime import date, datetime
from typing import Any

from universal_business.domain.availability.entities import AvailabilityBlock, AvailabilityRule
from universal_business.domain.availability.value_objects import AvailabilityStatus, BlockReason
from universal_business.domain.shared.value_objects.ids import (
    AvailabilityBlockId,
    AvailabilityRuleId,
    LocationId,
    ResourceId,
    TenantId,
)
from universal_business.domain.shared.value_objects.temporal import DateRange, TimeRange


def create_sqlite_availability_schema(connection: sqlite3.Connection) -> None:
    """Crear esquema inicial, sin migración de tablas preexistentes."""
    connection.execute("""CREATE TABLE IF NOT EXISTS availability_rules (
        tenant_id TEXT NOT NULL, id TEXT NOT NULL, location_id TEXT NOT NULL, resource_id TEXT,
        start_date TEXT NOT NULL, end_date TEXT NOT NULL, status TEXT NOT NULL,
        capacity INTEGER, intervals TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        PRIMARY KEY (tenant_id, id)
    )""")
    connection.execute("""CREATE TABLE IF NOT EXISTS availability_blocks (
        tenant_id TEXT NOT NULL, id TEXT NOT NULL, location_id TEXT NOT NULL, resource_id TEXT,
        start_date TEXT NOT NULL, end_date TEXT NOT NULL, status TEXT NOT NULL,
        reason TEXT NOT NULL, note TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        PRIMARY KEY (tenant_id, id)
    )""")
    for table in ("availability_rules", "availability_blocks"):
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS {table}_scope "
            f"ON {table} (tenant_id, location_id, start_date, end_date)"
        )


def _rule(row: tuple[Any, ...]) -> AvailabilityRule:
    data = json.loads(row[8])
    if (
        type(data) is not dict
        or type(data.get("version")) is not int
        or data.get("version") != 1
        or set(data) != {"version", "intervals"}
        or type(data["intervals"]) is not list
        or any(
            type(item) is not dict or set(item) != {"start", "end"} for item in data["intervals"]
        )
    ):
        raise ValueError("Intervalos de disponibilidad inválidos")
    intervals = [
        TimeRange(datetime.fromisoformat(item["start"]), datetime.fromisoformat(item["end"]))
        for item in data["intervals"]
    ]
    return AvailabilityRule(
        tenant_id=TenantId.from_raw(row[0]),
        id=AvailabilityRuleId.from_raw(row[1]),
        location_id=LocationId.from_raw(row[2]),
        resource_id=ResourceId.from_raw(row[3]) if row[3] is not None else None,
        effective_range=DateRange(date.fromisoformat(row[4]), date.fromisoformat(row[5])),
        status=AvailabilityStatus(row[6]),
        capacity=row[7],
        time_ranges=intervals,
        created_at=datetime.fromisoformat(row[9]),
        updated_at=datetime.fromisoformat(row[10]),
    )


def _block(row: tuple[Any, ...]) -> AvailabilityBlock:
    return AvailabilityBlock(
        tenant_id=TenantId.from_raw(row[0]),
        id=AvailabilityBlockId.from_raw(row[1]),
        location_id=LocationId.from_raw(row[2]),
        resource_id=ResourceId.from_raw(row[3]) if row[3] is not None else None,
        blocked_range=DateRange(date.fromisoformat(row[4]), date.fromisoformat(row[5])),
        status=AvailabilityStatus(row[6]),
        reason=BlockReason(row[7]),
        note=row[8],
        created_at=datetime.fromisoformat(row[9]),
        updated_at=datetime.fromisoformat(row[10]),
    )


class SqliteAvailabilityRepository:
    """Consultas completas por tenant/location, sin autorización ni migraciones.

    Lectura, modificaciones y confirmación deben compartir UoW SQLite con
    BEGIN IMMEDIATE. Las fechas y offsets se conservan; no el nombre IANA de
    cada intervalo. La búsqueda no determina disponibilidad ni adjudica.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def _save(self, table: str, values: tuple[object, ...], columns: str) -> None:
        if not self._connection.in_transaction:
            raise RuntimeError("La escritura requiere una transacción activa")
        result = self._connection.execute(
            f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            f"ON CONFLICT(tenant_id,id) DO UPDATE SET {columns} "
            f"WHERE {table}.location_id=excluded.location_id AND {table}.created_at=excluded.created_at",
            values,
        )
        if result.rowcount != 1:
            raise ValueError("No se puede cambiar ubicación o fecha de creación")

    def save_rule(self, rule: AvailabilityRule) -> None:
        if type(rule) is not AvailabilityRule or any(
            type(x) is not TimeRange for x in rule.time_ranges
        ):
            raise ValueError("Tipo de regla o intervalo no soportado")
        intervals = json.dumps(
            {
                "version": 1,
                "intervals": [
                    {"start": item.start.isoformat(), "end": item.end.isoformat()}
                    for item in rule.time_ranges
                ],
            },
            separators=(",", ":"),
        )
        values = (
            str(rule.tenant_id),
            str(rule.id),
            str(rule.location_id),
            str(rule.resource_id) if rule.resource_id else None,
            rule.effective_range.start.isoformat(),
            rule.effective_range.end.isoformat(),
            rule.status.value,
            rule.capacity,
            intervals,
            rule.created_at.isoformat(),
            rule.updated_at.isoformat(),
        )
        self._save(
            "availability_rules",
            values,
            "resource_id=excluded.resource_id,start_date=excluded.start_date,"
            "end_date=excluded.end_date,status=excluded.status,capacity=excluded.capacity,"
            "intervals=excluded.intervals,updated_at=excluded.updated_at",
        )

    def save_block(self, block: AvailabilityBlock) -> None:
        if type(block) is not AvailabilityBlock:
            raise ValueError("Tipo de bloqueo no soportado")
        values = (
            str(block.tenant_id),
            str(block.id),
            str(block.location_id),
            str(block.resource_id) if block.resource_id else None,
            block.blocked_range.start.isoformat(),
            block.blocked_range.end.isoformat(),
            block.status.value,
            block.reason.value,
            block.note,
            block.created_at.isoformat(),
            block.updated_at.isoformat(),
        )
        self._save(
            "availability_blocks",
            values,
            "resource_id=excluded.resource_id,start_date=excluded.start_date,"
            "end_date=excluded.end_date,status=excluded.status,reason=excluded.reason,"
            "note=excluded.note,updated_at=excluded.updated_at",
        )

    def list_rules_for_resource(
        self,
        *,
        tenant_id: TenantId,
        location_id: LocationId,
        resource_id: ResourceId | None = None,
        range: DateRange,
    ) -> list[AvailabilityRule]:
        sql = "SELECT * FROM availability_rules WHERE tenant_id=? AND location_id=? AND start_date<=? AND end_date>=?"
        params: list[object] = [
            str(tenant_id),
            str(location_id),
            range.end.isoformat(),
            range.start.isoformat(),
        ]
        if resource_id is not None:
            sql += " AND (resource_id IS NULL OR resource_id=?)"
            params.append(str(resource_id))
        return [_rule(row) for row in self._connection.execute(sql, params).fetchall()]

    def list_blocks(
        self, *, tenant_id: TenantId, location_id: LocationId, range: DateRange
    ) -> list[AvailabilityBlock]:
        rows = self._connection.execute(
            "SELECT * FROM availability_blocks WHERE tenant_id=? AND location_id=? AND start_date<=? AND end_date>=?",
            (str(tenant_id), str(location_id), range.end.isoformat(), range.start.isoformat()),
        ).fetchall()
        return [_block(row) for row in rows]
