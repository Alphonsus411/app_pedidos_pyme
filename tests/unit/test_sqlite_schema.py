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
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)
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
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)


def test_creation_failure_rolls_back_schema_and_version(tmp_path, monkeypatch):
    expected = sqlite_schema._expected_objects()
    monkeypatch.setattr(sqlite_schema, "_expected_objects", lambda: expected)

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
        assert list(executor.map(run, range(2))) == [1, 1]
