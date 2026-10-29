"""Inicialización segura de SQLite para el prototipo."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from universal_business.infrastructure import sqlite_schema
from universal_business.infrastructure.sqlite_schema import (
    IncompatibleSqliteSchemaError,
    initialize_sqlite_schema,
)


def test_initialize_reopen_idempotently_and_enforce_foreign_keys(tmp_path):
    path = tmp_path / "prototype.db"
    with sqlite3.connect(path) as connection:
        initialize_sqlite_schema(connection)
        assert connection.execute("PRAGMA user_version").fetchone() == (2,)
        assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {
            "locations",
            "resources",
            "customers",
            "reservations",
            "availability_rules",
            "availability_blocks",
            "idempotency",
            "transactional_outbox",
            "outbox_delivery",
            "outbox_quarantine",
            "orders",
        } <= tables
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO outbox_delivery(event_id) VALUES ('missing')")
        connection.rollback()
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone() == (0,)
        initialize_sqlite_schema(connection)
        assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
        initialize_sqlite_schema(connection)


@pytest.mark.parametrize(
    "schema,version",
    [
        ("CREATE TABLE unrelated (value TEXT)", 0),
        ("CREATE TABLE reservations (id TEXT)", 1),
        (None, 7),
    ],
)
def test_reject_legacy_or_incompatible_without_changes(tmp_path, schema, version):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        if schema:
            connection.execute(schema)
        connection.execute(f"PRAGMA user_version={version}")
        before = connection.execute(
            "SELECT type,name,sql FROM sqlite_master ORDER BY name"
        ).fetchall()
        with pytest.raises(IncompatibleSqliteSchemaError):
            initialize_sqlite_schema(connection)
        assert connection.execute("PRAGMA user_version").fetchone() == (version,)
        assert (
            connection.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name").fetchall()
            == before
        )


def test_reject_changed_schema_even_when_version_matches(tmp_path):
    with sqlite3.connect(tmp_path / "changed.db") as connection:
        initialize_sqlite_schema(connection)
        connection.execute("CREATE INDEX unexpected ON reservations(status)")
        with pytest.raises(IncompatibleSqliteSchemaError):
            initialize_sqlite_schema(connection)
        assert connection.execute("PRAGMA user_version").fetchone() == (2,)


def test_creation_failure_rolls_back_schema_and_version(tmp_path, monkeypatch):
    expected = sqlite_schema._expected_objects()
    monkeypatch.setattr(sqlite_schema, "_expected_objects", lambda *args: expected)

    def fail(connection):
        connection.execute("CREATE TABLE partial (id INTEGER)")
        raise RuntimeError("injected")

    monkeypatch.setattr(sqlite_schema, "_create_schema", fail)
    with sqlite3.connect(tmp_path / "failed.db") as connection:
        with pytest.raises(RuntimeError, match="injected"):
            initialize_sqlite_schema(connection)
        assert connection.execute("PRAGMA user_version").fetchone() == (0,)
        assert (
            connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
        )


def test_active_transaction_is_rejected_without_modifying_it(tmp_path):
    with sqlite3.connect(tmp_path / "active.db") as connection:
        connection.execute("BEGIN")
        connection.execute("CREATE TABLE caller_data (value TEXT)")
        with pytest.raises(RuntimeError, match="sin transacción"):
            initialize_sqlite_schema(connection)
        assert connection.in_transaction
        connection.rollback()
        assert connection.execute("PRAGMA user_version").fetchone() == (0,)


def test_parallel_initializers_are_serialized(tmp_path):
    path = tmp_path / "parallel.db"
    barrier = Barrier(2)

    def run(_):
        with sqlite3.connect(path, timeout=5) as connection:
            barrier.wait(timeout=5)
            initialize_sqlite_schema(connection)
            return connection.execute("PRAGMA user_version").fetchone()[0]

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(run, range(2))) == [2, 2]


def _make_v1(connection):
    sqlite_schema._create_schema(connection)
    connection.execute("PRAGMA user_version=1")
    connection.commit()


def test_explicit_migration_preserves_v1_data_and_allows_orders(tmp_path):
    path = tmp_path / "migration.db"
    with sqlite3.connect(path) as connection:
        _make_v1(connection)
        connection.execute(
            "INSERT INTO reservations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "tenant",
                "reservation",
                "business",
                "location",
                "customer",
                "resource",
                "start",
                "end",
                "start_utc",
                "end_utc",
                "draft",
                2,
                "keep",
                "created",
                "updated",
            ),
        )
        connection.execute("INSERT INTO transactional_outbox VALUES ('event', X'010203')")
        connection.execute(
            "INSERT INTO idempotency VALUES ('tenant', 'key', 'digest', 'token', 'reserved', NULL)"
        )
        connection.commit()
        before = (
            connection.execute("SELECT * FROM reservations").fetchall(),
            connection.execute("SELECT * FROM transactional_outbox").fetchall(),
            connection.execute("SELECT * FROM idempotency").fetchall(),
        )
        with pytest.raises(IncompatibleSqliteSchemaError):
            initialize_sqlite_schema(connection)
        sqlite_schema.migrate_sqlite_v1_to_v2(connection)
        assert connection.execute("PRAGMA user_version").fetchone() == (2,)
        assert before == (
            connection.execute("SELECT * FROM reservations").fetchall(),
            connection.execute("SELECT * FROM transactional_outbox").fetchall(),
            connection.execute("SELECT * FROM idempotency").fetchall(),
        )
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name='orders'"
        ).fetchone() == ("orders",)
        sqlite_schema.migrate_sqlite_v1_to_v2(connection)
        initialize_sqlite_schema(connection)
    with sqlite3.connect(path) as connection:
        initialize_sqlite_schema(connection)
        assert connection.execute("SELECT payload FROM transactional_outbox").fetchone() == (
            b"\x01\x02\x03",
        )


def test_modified_v1_rejected_without_data_loss(tmp_path):
    with sqlite3.connect(tmp_path / "modified.db") as connection:
        _make_v1(connection)
        connection.execute("CREATE TABLE unknown (data TEXT)")
        connection.execute("INSERT INTO unknown VALUES ('keep')")
        connection.commit()
        with pytest.raises(IncompatibleSqliteSchemaError):
            sqlite_schema.migrate_sqlite_v1_to_v2(connection)
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)
        assert connection.execute("SELECT * FROM unknown").fetchall() == [("keep",)]
        assert (
            connection.execute("SELECT name FROM sqlite_master WHERE name='orders'").fetchone()
            is None
        )


def test_failed_migration_rolls_back_schema_and_data(tmp_path, monkeypatch):
    with sqlite3.connect(tmp_path / "failure.db") as connection:
        _make_v1(connection)
        connection.execute("INSERT INTO transactional_outbox VALUES ('event', X'01')")
        connection.commit()
        v1, v2 = sqlite_schema._expected_objects(1), sqlite_schema._expected_objects(2)
        monkeypatch.setattr(
            sqlite_schema, "_expected_objects", lambda version: {1: v1, 2: v2}[version]
        )

        def fail(connection):
            connection.execute("CREATE TABLE orders (id TEXT)")
            raise RuntimeError("injected migration failure")

        monkeypatch.setattr(sqlite_schema, "create_sqlite_orders_schema", fail)
        with pytest.raises(RuntimeError, match="injected migration failure"):
            sqlite_schema.migrate_sqlite_v1_to_v2(connection)
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)
        assert (
            connection.execute("SELECT name FROM sqlite_master WHERE name='orders'").fetchone()
            is None
        )
        assert connection.execute("SELECT * FROM transactional_outbox").fetchall() == [
            ("event", b"\x01")
        ]


def test_parallel_v1_migrations_are_serialized(tmp_path):
    path = tmp_path / "parallel_migration.db"
    with sqlite3.connect(path) as connection:
        _make_v1(connection)
    barrier = Barrier(2)

    def run(_):
        with sqlite3.connect(path, timeout=5) as connection:
            barrier.wait(timeout=5)
            sqlite_schema.migrate_sqlite_v1_to_v2(connection)
            return connection.execute("PRAGMA user_version").fetchone()[0]

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(run, range(2))) == [2, 2]
