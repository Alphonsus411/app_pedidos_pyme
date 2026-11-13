"""F3.21: rejected SQLite snapshots must never overwrite a valid test database."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest
from test_staff_order_transitions import _counts, _setup, _status
from test_staff_sqlite_backup_restore import _backup, _verify_database


def _validate_candidate(path: Path) -> None:
    # The read-only URI avoids creating a missing candidate during validation.
    if not path.is_file():
        raise ValueError("Backup candidate is missing")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchall()
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    required = {"orders", "idempotency", "transactional_outbox"}
    if integrity != [("ok",)] or foreign_keys:
        raise ValueError("Backup candidate failed SQLite integrity validation")
    if version != 3 or not required.issubset(tables):
        raise ValueError("Backup candidate has an incompatible schema")


def _restore_in_test(candidate: Path, destination: Path) -> None:
    """Test-only staging: do not replace a destination before verification."""
    _validate_candidate(candidate)
    handle, name = tempfile.mkstemp(
        prefix="sqlite-restore-", suffix=".db", dir=destination.parent
    )
    os.close(handle)
    staging = Path(name)
    try:
        with sqlite3.connect(candidate) as source:
            with sqlite3.connect(staging) as target:
                source.backup(target)
        _validate_candidate(staging)
        os.replace(staging, destination)
    finally:
        staging.unlink(missing_ok=True)


@pytest.mark.parametrize(
    "damage",
    ["missing", "empty", "invalid-header", "truncated", "missing-schema", "wrong-version"],
)
def test_invalid_backup_never_replaces_healthy_database(tmp_path: Path, damage: str) -> None:
    source = tmp_path / "source.db"
    backup = tmp_path / "backup.db"
    destination = tmp_path / "destination.db"
    client, _, _, order_id, other_id = _setup(str(source))
    del client
    _backup(source, backup)
    _backup(source, destination)
    before_bytes = destination.read_bytes()
    before_counts = _counts(str(destination))
    candidate = tmp_path / "candidate.db"

    if damage == "empty":
        candidate.write_bytes(b"")
    elif damage == "invalid-header":
        candidate.write_bytes(b"this-is-not-a-sqlite-database" * 10)
    elif damage == "truncated":
        candidate.write_bytes(backup.read_bytes()[:100])
    elif damage in {"missing-schema", "wrong-version"}:
        with sqlite3.connect(candidate) as connection:
            connection.execute("PRAGMA user_version = 3")
            if damage == "wrong-version":
                connection.execute("PRAGMA user_version = 99")

    with pytest.raises((ValueError, sqlite3.DatabaseError)):
        _restore_in_test(candidate, destination)

    assert destination.read_bytes() == before_bytes
    _verify_database(destination)
    assert _counts(str(destination)) == before_counts
    assert _status(str(destination), order_id) == "draft"
    assert _status(str(destination), other_id) == "draft"
    assert list(tmp_path.glob("sqlite-restore-*.db")) == []


def test_valid_backup_restores_to_staging_then_replaces(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    candidate = tmp_path / "candidate.db"
    destination = tmp_path / "destination.db"
    _client, _sessions, _csrf, first_id, other_id = _setup(str(source))
    _backup(source, candidate)
    _backup(source, destination)
    # Verify the valid candidate is read-only checked and copied independently.
    _restore_in_test(candidate, destination)
    _verify_database(destination)
    assert _status(str(destination), first_id) == "draft"
    assert _status(str(destination), other_id) == "draft"
    assert _counts(str(destination)) == _counts(str(candidate))
    assert list(tmp_path.glob("sqlite-restore-*.db")) == []
