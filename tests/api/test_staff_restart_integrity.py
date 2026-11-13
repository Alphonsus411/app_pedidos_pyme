"""F3.19: SQLite integrity and restart behavior with synthetic staff orders."""

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


@pytest.mark.parametrize("precommitted", [False, True])
def test_restart_integrity(tmp_path, precommitted: bool) -> None:
    path = str(tmp_path / "restart-lab.db")
    client, sessions, csrf, order_id, other_id = _setup(path)
    initial = _counts(path)
    key = "restart-transition-0001"
    worker = Path(__file__).with_name("staff_transition_process_worker.py")
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")

    def run_worker(mode: str) -> None:
        result = subprocess.run(
            [sys.executable, str(worker), mode, path, order_id, key],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            cwd=root,
            env=env,
        )
        expected = 17 if mode == "before" else 18
        assert result.returncode == expected, result.stderr

    def verify_integrity() -> None:
        with sqlite3.connect(path) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchall()
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            version = connection.execute("PRAGMA user_version").fetchone()[0]
        assert integrity == [("ok",)]
        assert foreign_keys == []
        assert version == 3

    if precommitted:
        roles = frozenset({StaffRole.MANAGE_ORDERS})
        token = _authenticate(client, sessions, roles=roles)
        route = f"{FIRST_ROUTE}/{order_id}/transitions"
        response = client.post(
            route,
            json={"action": "validate"},
            headers=_headers(csrf, token, key=key),
        )
        assert response.status_code == 200
    else:
        run_worker("before")
        assert _status(path, order_id) == "draft"
        assert _counts(path) == initial

    verify_integrity()
    run_worker("after")
    verify_integrity()
    run_worker("after")
    verify_integrity()
    assert _status(path, order_id) == "validated"
    assert _status(path, other_id) == "draft"
    assert _counts(path) == (initial[0] + 1, initial[1] + 1)
