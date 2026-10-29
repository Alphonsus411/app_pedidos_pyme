"""Persistencia SQLite de ubicaciones, horarios y ámbito."""

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from universal_business.domain.business.entities import Location
from universal_business.domain.business.value_objects import (
    Address,
    ContactInfo,
    LocationStatus,
    OperatingHours,
)
from universal_business.domain.shared.value_objects.ids import BusinessId, LocationId, TenantId
from universal_business.domain.shared.value_objects.temporal import TimeRange
from universal_business.infrastructure.sqlite_locations import (
    SqliteLocationRepository,
    create_sqlite_locations_schema,
)
from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork


@pytest.fixture
def location() -> Location:
    start = datetime(2026, 10, 26, 9, tzinfo=UTC)
    return Location(
        id=LocationId.generate(),
        tenant_id=TenantId.generate(),
        business_id=BusinessId.generate(),
        name="Local",
        address=Address(country_code="ES", city="Madrid"),
        timezone="Europe/Madrid",
        status=LocationStatus.OPEN,
        operating_hours=OperatingHours(
            by_day={"MONDAY": [TimeRange(start, start + timedelta(hours=8))]}
        ),
        contact_info=ContactInfo(email="local@example.org"),
    )


def test_roundtrip_scope_update_and_rollback(tmp_path: Path, location: Location) -> None:
    path = tmp_path / "locations.db"
    with sqlite3.connect(path) as connection:
        create_sqlite_locations_schema(connection)
        repo = SqliteLocationRepository(connection)
        with pytest.raises(RuntimeError, match="transacción"):
            repo.save(location)
        with SqliteUnitOfWork(connection):
            repo.save(location)
        assert (
            repo.get(
                tenant_id=location.tenant_id,
                business_id=location.business_id,
                location_id=location.id,
            )
            is None
        )
        with SqliteUnitOfWork(connection) as uow:
            repo.save(location)
            with sqlite3.connect(path) as reader:
                assert (
                    SqliteLocationRepository(reader).get(
                        tenant_id=location.tenant_id,
                        business_id=location.business_id,
                        location_id=location.id,
                    )
                    is None
                )
            uow.commit()
        assert (
            repo.get(
                tenant_id=location.tenant_id,
                business_id=location.business_id,
                location_id=location.id,
            )
            == location
        )
        assert (
            repo.get(
                tenant_id=TenantId.generate(),
                business_id=location.business_id,
                location_id=location.id,
            )
            is None
        )
        assert (
            repo.get(
                tenant_id=location.tenant_id,
                business_id=BusinessId.generate(),
                location_id=location.id,
            )
            is None
        )
        changed = replace(location, name="Local 2")
        with SqliteUnitOfWork(connection) as uow:
            repo.save(changed)
            uow.commit()
        assert repo.list_by_business(
            tenant_id=location.tenant_id,
            business_id=location.business_id,
            status=LocationStatus.OPEN,
        ) == [changed]
        with pytest.raises(ValueError, match="negocio"):
            with SqliteUnitOfWork(connection):
                repo.save(replace(location, business_id=BusinessId.generate()))


def test_corrupt_weekdays_fail_closed(tmp_path: Path, location: Location) -> None:
    with sqlite3.connect(tmp_path / "locations.db") as connection:
        create_sqlite_locations_schema(connection)
        repo = SqliteLocationRepository(connection)
        location.operating_hours.by_day.clear()
        with pytest.raises(ValueError, match="Días"):
            with SqliteUnitOfWork(connection):
                repo.save(location)
