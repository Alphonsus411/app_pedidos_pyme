"""Propiedad y recuperación conservadora de claves SQLite."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from universal_business.application.idempotency import IdempotencyKey
from universal_business.application.reservations.creation import ReservationDraftCreated
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    ReservationId,
    ResourceId,
    TenantId,
)
from universal_business.infrastructure.sqlite_idempotency import (
    SqliteReservationIdempotencyStore,
    create_sqlite_idempotency_schema,
)
from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "idem.db"
    with sqlite3.connect(path) as connection:
        create_sqlite_idempotency_schema(connection)
    return path


def test_reservation_commit_replay_and_scope(db: Path) -> None:
    tenant, key = TenantId.generate(), IdempotencyKey(value="test-key-123")
    result = ReservationDraftCreated(
        tenant_id=tenant,
        business_id=BusinessId.generate(),
        location_id=LocationId.generate(),
        reservation_id=ReservationId.generate(),
        resource_id=ResourceId.generate(),
    )
    with sqlite3.connect(db) as connection:
        store = SqliteReservationIdempotencyStore(connection)
        with SqliteUnitOfWork(connection) as uow:
            assert store.reserve(tenant, key, "digest")
            uow.commit()
        store.complete(tenant, key, "digest", result)
    with sqlite3.connect(db) as connection:
        store = SqliteReservationIdempotencyStore(connection)
        with SqliteUnitOfWork(connection):
            assert not store.reserve(tenant, key, "digest")
            assert store.get(tenant, key) == ("digest", result)
            assert store.get(TenantId.generate(), key) is None
            store.release(tenant, key)
        assert store.get(tenant, key) == ("digest", result)


def test_committed_in_progress_is_retained_after_restart(db: Path) -> None:
    tenant, key = TenantId.generate(), IdempotencyKey(value="test-key-123")
    with sqlite3.connect(db) as connection:
        store = SqliteReservationIdempotencyStore(connection)
        with SqliteUnitOfWork(connection) as uow:
            assert store.reserve(tenant, key, "digest")
            uow.commit()
    with sqlite3.connect(db) as connection:
        another = SqliteReservationIdempotencyStore(connection)
        with SqliteUnitOfWork(connection):
            assert not another.reserve(tenant, key, "digest")
            assert another.get(tenant, key) is None
            another.release(tenant, key)
        assert connection.execute("SELECT state FROM idempotency").fetchone() == ("reserved",)


def test_complete_failure_keeps_reservation(db: Path) -> None:
    tenant, key = TenantId.generate(), IdempotencyKey(value="test-key-123")
    with sqlite3.connect(db) as connection:
        store = SqliteReservationIdempotencyStore(connection)
        with SqliteUnitOfWork(connection) as uow:
            assert store.reserve(tenant, key, "digest")
            uow.commit()
        with pytest.raises(ValueError, match="Resultado no soportado"):
            store.complete(tenant, key, "digest", object())
        assert connection.execute("SELECT state FROM idempotency").fetchone() == ("reserved",)


def test_rollback_and_foreign_release_cannot_delete_new_owner(db: Path) -> None:
    tenant, key = TenantId.generate(), IdempotencyKey(value="test-key-123")
    with sqlite3.connect(db) as first, sqlite3.connect(db) as second:
        owner = SqliteReservationIdempotencyStore(first)
        with SqliteUnitOfWork(first):
            assert owner.reserve(tenant, key, "digest")
        next_owner = SqliteReservationIdempotencyStore(second)
        with SqliteUnitOfWork(second) as uow:
            assert next_owner.reserve(tenant, key, "digest")
            uow.commit()
        owner.release(tenant, key)
        assert second.execute("SELECT state FROM idempotency").fetchone() == ("reserved",)


def test_concurrent_reserve_has_only_one_owner(db: Path) -> None:
    tenant, key = TenantId.generate(), IdempotencyKey(value="test-key-123")

    def claim(_: int) -> bool:
        with sqlite3.connect(db, timeout=5) as connection:
            store = SqliteReservationIdempotencyStore(connection)
            with SqliteUnitOfWork(connection) as uow:
                acquired = store.reserve(tenant, key, "digest")
                uow.commit()
                return acquired

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, range(2))) == [False, True]
