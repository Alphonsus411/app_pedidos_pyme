"""Pruebas del repositorio SQLite de recursos."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from universal_business.domain.resources.entities import Resource
from universal_business.domain.resources.value_objects import ResourceStatus, ResourceType
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    ResourceId,
    ResourceTypeId,
    TenantId,
)
from universal_business.infrastructure.sqlite_resources import (
    SqliteResourceRepository,
    create_sqlite_resources_schema,
)
from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "resources.db"
    with sqlite3.connect(path) as connection:
        create_sqlite_resources_schema(connection)
    return path


@pytest.fixture
def resource() -> Resource:
    return Resource(
        id=ResourceId.generate(),
        tenant_id=TenantId.generate(),
        business_id=BusinessId.generate(),
        resource_type_id=ResourceTypeId.generate(),
        location_id=LocationId.generate(),
        name="Sala",
        capacity=4,
    )


def test_roundtrip_scope_and_no_replayed_creation_event(db: Path, resource: Resource) -> None:
    with sqlite3.connect(db) as connection:
        repo = SqliteResourceRepository(connection)
        with SqliteUnitOfWork(connection) as uow:
            repo.save(resource)
            with sqlite3.connect(db) as reader:
                assert (
                    SqliteResourceRepository(reader).get(
                        tenant_id=resource.tenant_id,
                        business_id=resource.business_id,
                        resource_id=resource.id,
                    )
                    is None
                )
            uow.commit()
        result = repo.get(
            tenant_id=resource.tenant_id, business_id=resource.business_id, resource_id=resource.id
        )
        assert result == resource
        assert result is not None and result.domain_events == []
        assert (
            repo.get(
                tenant_id=TenantId.generate(),
                business_id=resource.business_id,
                resource_id=resource.id,
            )
            is None
        )
        assert (
            repo.get(
                tenant_id=resource.tenant_id,
                business_id=BusinessId.generate(),
                resource_id=resource.id,
            )
            is None
        )


def test_rollback_and_cannot_change_business(db: Path, resource: Resource) -> None:
    with sqlite3.connect(db) as connection:
        repo = SqliteResourceRepository(connection)
        with pytest.raises(RuntimeError, match="transacción"):
            repo.save(resource)
        with SqliteUnitOfWork(connection):
            repo.save(resource)
        assert (
            repo.get(
                tenant_id=resource.tenant_id,
                business_id=resource.business_id,
                resource_id=resource.id,
            )
            is None
        )
        with SqliteUnitOfWork(connection) as uow:
            repo.save(resource)
            uow.commit()
        with pytest.raises(ValueError, match="negocio"):
            with SqliteUnitOfWork(connection):
                repo.save(replace(resource, business_id=BusinessId.generate()))


def test_lists_filter_scope_status_location_and_type(db: Path, resource: Resource) -> None:
    another = replace(
        resource, id=ResourceId.generate(), location_id=None, status=ResourceStatus.INACTIVE
    )
    other_business = replace(resource, id=ResourceId.generate(), business_id=BusinessId.generate())
    with sqlite3.connect(db) as connection:
        repo = SqliteResourceRepository(connection)
        with SqliteUnitOfWork(connection) as uow:
            for item in (resource, another, other_business):
                repo.save(item)
            uow.commit()
        assert repo.list_active(tenant_id=resource.tenant_id, business_id=resource.business_id) == [
            resource
        ]
        assert repo.list_by_location(
            tenant_id=resource.tenant_id,
            business_id=resource.business_id,
            location_id=resource.location_id,
            resource_type_id=resource.resource_type_id,
        ) == [resource]
        assert (
            len(
                repo.list_by_business(
                    tenant_id=resource.tenant_id, business_id=resource.business_id
                )
            )
            == 2
        )
        with pytest.raises(ValueError, match="legacy"):
            repo.list_by_location(
                tenant_id=resource.tenant_id,
                business_id=resource.business_id,
                location_id=resource.location_id,
                resource_type=ResourceType.ROOM,
            )
