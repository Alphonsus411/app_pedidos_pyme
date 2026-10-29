"""Persistencia SQLite de recursos del prototipo."""

import sqlite3
from datetime import datetime
from typing import Any

from universal_business.domain.resources.entities import Resource
from universal_business.domain.resources.value_objects import ResourceStatus, ResourceType
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    ResourceId,
    ResourceTypeId,
    TenantId,
)


def create_sqlite_resources_schema(connection: sqlite3.Connection) -> None:
    """Crear el esquema inicial; el versionado de migraciones es posterior."""
    connection.execute("""CREATE TABLE IF NOT EXISTS resources (
        tenant_id TEXT NOT NULL, id TEXT NOT NULL, business_id TEXT NOT NULL,
        resource_type_id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL,
        location_id TEXT, capacity INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        PRIMARY KEY (tenant_id, id)
    )""")
    connection.execute("""CREATE INDEX IF NOT EXISTS resources_scope
        ON resources (tenant_id, business_id, location_id, status, resource_type_id)""")


def _from_row(row: tuple[Any, ...]) -> Resource:
    resource = Resource(
        tenant_id=TenantId.from_raw(row[0]),
        id=ResourceId.from_raw(row[1]),
        business_id=BusinessId.from_raw(row[2]),
        resource_type_id=ResourceTypeId.from_raw(row[3]),
        name=row[4],
        status=ResourceStatus(row[5]),
        location_id=LocationId.from_raw(row[6]) if row[6] is not None else None,
        capacity=row[7],
        created_at=datetime.fromisoformat(row[8]),
        updated_at=datetime.fromisoformat(row[9]),
    )
    # La reconstrucción no crea un nuevo evento de dominio.
    resource.clear_domain_events()
    return resource


class SqliteResourceRepository:
    """Filtra por tenant/business; escritura exige transacción activa.

    Para concurrencia los cambios de recurso y reservas deben compartir UoW
    con protección compatible. No valida autorización ni referencias a otras
    tablas. El tipo legacy ResourceType no tiene mapeo persistido y se rechaza.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(
        self, /, *, tenant_id: TenantId, business_id: BusinessId, resource_id: ResourceId
    ) -> Resource | None:
        row = self._connection.execute(
            "SELECT * FROM resources WHERE tenant_id=? AND business_id=? AND id=?",
            (str(tenant_id), str(business_id), str(resource_id)),
        ).fetchone()
        return _from_row(row) if row else None

    def save(self, resource: Resource, /) -> None:
        if not self._connection.in_transaction:
            raise RuntimeError("La escritura requiere una transacción activa")
        if type(resource) is not Resource:
            raise ValueError("Subtipo de recurso no soportado")
        params = (
            str(resource.tenant_id),
            str(resource.id),
            str(resource.business_id),
            str(resource.resource_type_id),
            resource.name,
            resource.status.value,
            str(resource.location_id) if resource.location_id else None,
            resource.capacity,
            resource.created_at.isoformat(),
            resource.updated_at.isoformat(),
        )
        result = self._connection.execute(
            """INSERT INTO resources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id,id) DO UPDATE SET resource_type_id=excluded.resource_type_id,
            name=excluded.name, status=excluded.status, location_id=excluded.location_id,
            capacity=excluded.capacity, updated_at=excluded.updated_at
            WHERE resources.business_id=excluded.business_id AND resources.created_at=excluded.created_at""",
            params,
        )
        if result.rowcount != 1:
            raise ValueError("No se puede cambiar el negocio o fecha de creación del recurso")

    def list_by_business(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId | None = None,
        status: ResourceStatus | None = None,
        resource_type_id: ResourceTypeId | None = None,
    ) -> list[Resource]:
        sql = "SELECT * FROM resources WHERE tenant_id=? AND business_id=?"
        params: list[object] = [str(tenant_id), str(business_id)]
        for column, value in (
            ("location_id", location_id),
            ("status", status),
            ("resource_type_id", resource_type_id),
        ):
            if value is not None:
                sql += f" AND {column}=?"
                params.append(str(value))
        return [_from_row(row) for row in self._connection.execute(sql, params).fetchall()]

    def list_by_location(
        self,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId,
        status: ResourceStatus | None = None,
        resource_type: ResourceType | None = None,
        resource_type_id: ResourceTypeId | None = None,
    ) -> list[Resource]:
        if resource_type is not None:
            raise ValueError("El filtro ResourceType legacy no tiene mapeo")
        return self.list_by_business(
            tenant_id=tenant_id,
            business_id=business_id,
            location_id=location_id,
            status=status,
            resource_type_id=resource_type_id,
        )

    def list_active(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId | None = None,
        resource_type_id: ResourceTypeId | None = None,
    ) -> list[Resource]:
        return self.list_by_business(
            tenant_id=tenant_id,
            business_id=business_id,
            location_id=location_id,
            status=ResourceStatus.ACTIVE,
            resource_type_id=resource_type_id,
        )
