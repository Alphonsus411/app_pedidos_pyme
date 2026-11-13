"""F3.25: isolated transactional, monotonic checkpoint persistence laboratory."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


def _init_checkpoint(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE checkpoint ("
            "slot INTEGER PRIMARY KEY CHECK (slot = 1), "
            "sequence INTEGER NOT NULL CHECK (sequence > 0), "
            "backup_id TEXT NOT NULL CHECK (length(backup_id) > 0))"
        )


def _read_checkpoint(path: Path) -> tuple[int, str] | None:
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT sequence, backup_id FROM checkpoint WHERE slot = 1"
        ).fetchone()
    return None if row is None else (int(row[0]), str(row[1]))


def _publish_checkpoint(
    path: Path,
    sequence: int,
    backup_id: str,
    *,
    inject_failure: bool = False,
) -> tuple[int, str]:
    if type(sequence) is not int or sequence < 1 or not backup_id:
        raise ValueError("Invalid checkpoint")
    with sqlite3.connect(path, timeout=5) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT sequence, backup_id FROM checkpoint WHERE slot = 1"
        ).fetchone()
        if row is None:
            if sequence != 1:
                raise ValueError("First checkpoint must have sequence one")
            connection.execute(
                "INSERT INTO checkpoint(slot, sequence, backup_id) VALUES (1, ?, ?)",
                (sequence, backup_id),
            )
        else:
            current_sequence, current_id = int(row[0]), str(row[1])
            if (sequence, backup_id) == (current_sequence, current_id):
                return sequence, backup_id
            if sequence != current_sequence + 1:
                raise ValueError("Non-monotonic or skipped checkpoint")
            connection.execute(
                "UPDATE checkpoint SET sequence = ?, backup_id = ? WHERE slot = 1",
                (sequence, backup_id),
            )
        if inject_failure:
            raise RuntimeError("Injected failure before commit")
    return sequence, backup_id


def test_checkpoint_persists_and_refuses_rollback(tmp_path: Path) -> None:
    path = tmp_path / "trusted-checkpoint.db"
    _init_checkpoint(path)
    assert _read_checkpoint(path) is None
    assert _publish_checkpoint(path, 1, "backup-one") == (1, "backup-one")
    assert _publish_checkpoint(path, 1, "backup-one") == (1, "backup-one")
    assert _publish_checkpoint(path, 2, "backup-two") == (2, "backup-two")
    assert _read_checkpoint(path) == (2, "backup-two")
    for sequence, identity in ((1, "backup-one"), (2, "different"), (4, "skip")):
        with pytest.raises(ValueError):
            _publish_checkpoint(path, sequence, identity)
    assert _read_checkpoint(path) == (2, "backup-two")
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]


def test_checkpoint_rollback_on_fault_and_retry(tmp_path: Path) -> None:
    path = tmp_path / "trusted-checkpoint.db"
    _init_checkpoint(path)
    _publish_checkpoint(path, 1, "backup-one")
    with pytest.raises(RuntimeError, match="Injected failure"):
        _publish_checkpoint(path, 2, "backup-two", inject_failure=True)
    assert _read_checkpoint(path) == (1, "backup-one")
    assert _publish_checkpoint(path, 2, "backup-two") == (2, "backup-two")
    assert _read_checkpoint(path) == (2, "backup-two")


def test_concurrent_competing_checkpoint_writes_have_one_winner(
    tmp_path: Path,
) -> None:
    path = tmp_path / "trusted-checkpoint.db"
    _init_checkpoint(path)
    _publish_checkpoint(path, 1, "backup-one")

    def publish(identity: str) -> bool:
        try:
            _publish_checkpoint(path, 2, identity)
        except ValueError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, ("backup-two-A", "backup-two-B")))
    assert sorted(results) == [False, True]
    persisted = _read_checkpoint(path)
    assert persisted in ((2, "backup-two-A"), (2, "backup-two-B"))
    assert _read_checkpoint(path) == persisted
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM checkpoint").fetchone()[0] == 1


@pytest.mark.parametrize("sequence", (0, -1, 1.5, True))
def test_invalid_sequence_fails_closed(tmp_path: Path, sequence: object) -> None:
    path = tmp_path / "trusted-checkpoint.db"
    _init_checkpoint(path)
    with pytest.raises(ValueError):
        _publish_checkpoint(path, sequence, "backup-one")
    assert _read_checkpoint(path) is None
