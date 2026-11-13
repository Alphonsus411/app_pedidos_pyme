"""F3.20: verified SQLite backup snapshots and synthetic restoration."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from apps.api.app.staff_auth import StaffRole
from test_staff_order_transitions import (
    FIRST_ROUTE,
    _authenticate,
    _counts,
    _headers,
    _setup,
    _status,
)


def _verify_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchall()
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert integrity == [("ok",)]
    assert foreign_keys == []
    assert version == 3


def _backup(source: Path, destination: Path) -> None:
    # SQLite's online backup API creates a consistent database snapshot;
    # copying an open .db file byte-by-byte is not a safe substitute.
    with sqlite3.connect(source) as live:
        with sqlite3.connect(destination) as target:
            live.backup(target)
    _verify_database(destination)


@pytest.mark.parametrize("snapshot_after_commit", [False, True])
def test_backup_restore_reconciles_without_duplicate_writes(
    tmp_path: Path, snapshot_after_commit: bool
) -> None:
    source = tmp_path / "live.db"
    snapshot = tmp_path / "snapshot.db"
    restored = tmp_path / "restored.db"
    client, sessions, csrf, first_id, second_id = _setup(str(source))
    initial = _counts(str(source))
    key = "backup-restore-0001"
    roles = frozenset({StaffRole.MANAGE_ORDERS})
    first_token = _authenticate(client, sessions, roles=roles)
    first_route = f"{FIRST_ROUTE}/{first_id}/transitions"
    first_headers = _headers(csrf, first_token, key=key)

    if snapshot_after_commit:
        first = client.post(first_route, json={"action": "validate"}, headers=first_headers)
        assert first.status_code == 200

    _backup(source, snapshot)
    snapshot_status = "validated" if snapshot_after_commit else "draft"
    snapshot_delta = int(snapshot_after_commit)
    assert _status(str(snapshot), first_id) == snapshot_status
    assert _counts(str(snapshot)) == (
        initial[0] + snapshot_delta,
        initial[1] + snapshot_delta,
    )

    # The live system continues evolving AFTER snapshot creation.
    # This must not mutate either backup or restored copy.
    if not snapshot_after_commit:
        first = client.post(
            first_route, json={"action": "validate"}, headers=first_headers
        )
        assert first.status_code == 200
    second_token = _authenticate(client, sessions, roles=roles, business="second")
    second_route = f"/api/v1/staff/businesses/second/locations/main/orders/{second_id}/transitions"
    second_headers = _headers(csrf, second_token, business="second", key="backup-second-0001")
    second = client.post(second_route, json={"action": "validate"}, headers=second_headers)
    assert second.status_code == 200
    assert _status(str(source), first_id) == "validated"
    assert _status(str(source), second_id) == "validated"
    assert _counts(str(source)) == (initial[0] + 2, initial[1] + 2)

    _backup(snapshot, restored)
    _verify_database(source)
    _verify_database(snapshot)
    _verify_database(restored)
    assert _status(str(restored), first_id) == snapshot_status
    assert _status(str(restored), second_id) == "draft"
    assert _counts(str(restored)) == (
        initial[0] + snapshot_delta,
        initial[1] + snapshot_delta,
    )

    # Reconstruct an independent staff HTTP app and SQLite connection in a
    # fresh Python process after restoring the snapshot to a new file.
    worker = Path(__file__).with_name("staff_transition_process_worker.py")
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    for _ in range(2):
        process = subprocess.run(
            [sys.executable, str(worker), "after", str(restored), first_id, key],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            cwd=root,
            env=env,
        )
        assert process.returncode == 18, process.stderr
        _verify_database(restored)

    assert _status(str(restored), first_id) == "validated"
    assert _status(str(restored), second_id) == "draft"
    assert _counts(str(restored)) == (initial[0] + 1, initial[1] + 1)
    # Restoring and operating on a separate file does not roll back live data.
    assert _counts(str(source)) == (initial[0] + 2, initial[1] + 2)
    assert _status(str(snapshot), first_id) == snapshot_status
