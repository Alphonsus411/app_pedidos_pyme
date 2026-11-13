"""F3.17: controlled SQLite commit ambiguity at the staff HTTP boundary."""

from __future__ import annotations

import sqlite3

import pytest
from apps.api.app.local_staff_sessions import COOKIE_NAME
from apps.api.app.staff_auth import StaffRole
from fastapi.testclient import TestClient

from test_staff_order_transitions import (
    FIRST_ROUTE,
    _authenticate,
    _counts,
    _headers,
    _setup,
    _status,
)



@pytest.mark.parametrize(
    "raise_after_commit",
    [False, True],
    ids=["pre-commit", "post-commit"],
)
def test_same_key_reconciliation_after_uncertain_commit(
    tmp_path, raise_after_commit: bool
) -> None:
    path = str(tmp_path / "uncertain-commit.db")
    armed = {"value": True}

    class FaultyCommitConnection(sqlite3.Connection):
        def commit(self) -> None:
            count = getattr(self, "_lab_commit_count", 0) + 1
            self._lab_commit_count = count
            # The first commit is schema validation; the second is the UoW.
            if count == 2 and armed["value"]:
                armed["value"] = False
                if raise_after_commit:
                    super().commit()
                raise sqlite3.OperationalError("synthetic uncertain commit")
            super().commit()

    def connect() -> sqlite3.Connection:
        return sqlite3.connect(path, factory=FaultyCommitConnection)

    base, sessions, csrf, order_id, foreign_id = _setup(path, transition_connect=connect)
    token = _authenticate(base, sessions, roles=frozenset({StaffRole.MANAGE_ORDERS}))
    route = f"{FIRST_ROUTE}/{order_id}/transitions"
    headers = _headers(csrf, token, key="uncertain-commit-0001")
    before = _counts(path)

    with TestClient(base.app, raise_server_exceptions=False) as client:
        client.cookies.set(COOKIE_NAME, token, path="/")
        uncertain = client.post(route, json={"action": "validate"}, headers=headers)
        assert uncertain.status_code == 500
        assert uncertain.json()["error"]["code"] == "internal_error"
        assert uncertain.headers["X-Request-ID"]
        assert "sqlite" not in uncertain.text.lower()
        assert "commit" not in uncertain.text.lower()

        delta = 1 if raise_after_commit else 0
        assert _status(path, order_id) == ("validated" if delta else "draft")
        assert _status(path, foreign_id) == "draft"
        assert _counts(path) == (before[0] + delta, before[1] + delta)

        retry = client.post(route, json={"action": "validate"}, headers=headers)
        assert retry.status_code == 200
        assert retry.json() == {"id": order_id, "status": "validated"}
        assert _counts(path) == (before[0] + 1, before[1] + 1)
        replay = client.post(route, json={"action": "validate"}, headers=headers)
        assert replay.status_code == 200
        assert _counts(path) == (before[0] + 1, before[1] + 1)

        conflict = client.post(
            route,
            json={"action": "validate"},
            headers=_headers(csrf, token, key="uncertain-commit-0002"),
        )
        assert conflict.status_code == 409
        assert _counts(path) == (before[0] + 1, before[1] + 1)
