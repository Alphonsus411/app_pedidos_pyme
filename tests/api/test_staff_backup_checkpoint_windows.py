"""F3.26: observe partial backup/checkpoint publication, never repair implicitly."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from test_staff_checkpoint_monotonic import (
    _init_checkpoint,
    _publish_checkpoint,
    _read_checkpoint,
)


def _create_source(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        sql = "CREATE TABLE synthetic_orders(id INTEGER PRIMARY KEY)"
        connection.execute(sql)
        connection.execute("INSERT INTO synthetic_orders(id) VALUES (1)")


def _init_intents(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE intents("
            "sequence INTEGER PRIMARY KEY, "
            "backup_id TEXT NOT NULL UNIQUE, "
            "state TEXT NOT NULL CHECK(state IN ('pending', 'confirmed')))"
        )


def _register(path: Path, sequence: int, backup_id: str) -> None:
    with sqlite3.connect(path) as connection:
        sql = "INSERT INTO intents(sequence, backup_id, state) VALUES (?, ?, 'pending')"
        connection.execute(sql, (sequence, backup_id))


def _finalize(path: Path, sequence: int, backup_id: str) -> None:
    with sqlite3.connect(path) as connection:
        sql = "UPDATE intents SET state='confirmed' "
        sql += "WHERE sequence=? AND backup_id=? AND state='pending'"
        cursor = connection.execute(sql, (sequence, backup_id))
        if cursor.rowcount != 1:
            raise ValueError("Expected one pending backup intent")


def _snapshot(source: Path, destination: Path) -> None:
    with sqlite3.connect(source) as origin:
        with sqlite3.connect(destination) as target:
            origin.backup(target)


def _observe(
    ledger: Path,
    checkpoint: Path,
    snapshot: Path,
    sequence: int,
    backup_id: str,
) -> str:
    """Read-only classification; never publish or overwrite an artifact."""
    with sqlite3.connect(ledger) as connection:
        query = "SELECT backup_id, state FROM intents WHERE sequence=?"
        row = connection.execute(query, (sequence,)).fetchone()
    published = _read_checkpoint(checkpoint)
    if row is None:
        return "orphan" if snapshot.is_file() else "absent"
    if row[0] != backup_id:
        return "identity_mismatch"
    if not snapshot.is_file():
        return "missing_artifact"
    try:
        with sqlite3.connect(snapshot.as_uri() + "?mode=ro", uri=True) as copy:
            integrity = copy.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.DatabaseError:
        return "invalid_artifact"
    if integrity != [("ok",)]:
        return "invalid_artifact"
    expected = (sequence, backup_id)
    if published is not None and published != expected:
        return "checkpoint_mismatch"
    if row[1] == "confirmed":
        if published == expected:
            return "confirmed"
        return "unconfirmed_checkpoint"
    if published == expected:
        return "published_not_finalized"
    return "pending_unpublished"


def _state(ledger: Path, checkpoint: Path, snapshot: Path) -> str:
    return _observe(ledger, checkpoint, snapshot, 1, "backup-one")


def _laboratory(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    source = tmp_path / "source.db"
    ledger = tmp_path / "intents.db"
    checkpoint = tmp_path / "checkpoint.db"
    snapshot = tmp_path / "backup-one.db"
    _create_source(source)
    _init_intents(ledger)
    _init_checkpoint(checkpoint)
    return source, ledger, checkpoint, snapshot


def test_backup_publication_windows_are_not_conflated(tmp_path: Path) -> None:
    source, ledger, checkpoint, snapshot = _laboratory(tmp_path)
    _register(ledger, 1, "backup-one")
    assert _state(ledger, checkpoint, snapshot) == "missing_artifact"
    _snapshot(source, snapshot)
    assert _state(ledger, checkpoint, snapshot) == "pending_unpublished"
    _publish_checkpoint(checkpoint, 1, "backup-one")
    assert _state(ledger, checkpoint, snapshot) == "published_not_finalized"
    _finalize(ledger, 1, "backup-one")
    assert _state(ledger, checkpoint, snapshot) == "confirmed"
    with sqlite3.connect(snapshot) as connection:
        rows = connection.execute("SELECT COUNT(*) FROM synthetic_orders")
        assert rows.fetchone()[0] == 1


def test_checkpoint_failure_preserves_pending(tmp_path: Path) -> None:
    source, ledger, checkpoint, snapshot = _laboratory(tmp_path)
    _register(ledger, 1, "backup-one")
    _snapshot(source, snapshot)
    with pytest.raises(RuntimeError, match="Injected failure"):
        _publish_checkpoint(checkpoint, 1, "backup-one", inject_failure=True)
    assert _read_checkpoint(checkpoint) is None
    assert _state(ledger, checkpoint, snapshot) == "pending_unpublished"
    # Explicit operator-driven retry, not an automatic observer side effect.
    _publish_checkpoint(checkpoint, 1, "backup-one")
    assert _state(ledger, checkpoint, snapshot) == "published_not_finalized"
    _finalize(ledger, 1, "backup-one")
    assert _state(ledger, checkpoint, snapshot) == "confirmed"


def test_publish_then_finalize_retries(tmp_path: Path) -> None:
    source, ledger, checkpoint, snapshot = _laboratory(tmp_path)
    _register(ledger, 1, "backup-one")
    _snapshot(source, snapshot)
    _publish_checkpoint(checkpoint, 1, "backup-one")
    assert _state(ledger, checkpoint, snapshot) == "published_not_finalized"
    published = _publish_checkpoint(checkpoint, 1, "backup-one")
    assert published == (1, "backup-one")
    with pytest.raises(ValueError):
        _publish_checkpoint(checkpoint, 1, "conflicting-backup")
    _finalize(ledger, 1, "backup-one")
    assert _state(ledger, checkpoint, snapshot) == "confirmed"


def test_orphan_and_missing_backup(tmp_path: Path) -> None:
    source, ledger, checkpoint, snapshot = _laboratory(tmp_path)
    _snapshot(source, snapshot)
    assert _state(ledger, checkpoint, snapshot) == "orphan"
    assert _read_checkpoint(checkpoint) is None
    _register(ledger, 1, "backup-one")
    _publish_checkpoint(checkpoint, 1, "backup-one")
    _finalize(ledger, 1, "backup-one")
    snapshot.unlink()
    assert _state(ledger, checkpoint, snapshot) == "missing_artifact"
    assert _read_checkpoint(checkpoint) == (1, "backup-one")


def test_invalid_or_mismatched_artifacts(tmp_path: Path) -> None:
    _source, ledger, checkpoint, snapshot = _laboratory(tmp_path)
    _register(ledger, 1, "backup-one")
    snapshot.write_bytes(b"not-a-sqlite-backup")
    assert _state(ledger, checkpoint, snapshot) == "invalid_artifact"
    observed = _observe(ledger, checkpoint, snapshot, 1, "different")
    assert observed == "identity_mismatch"
    assert _read_checkpoint(checkpoint) is None
    with sqlite3.connect(ledger) as connection:
        row = connection.execute("SELECT state FROM intents").fetchone()
        assert row == ("pending",)
