"""Regresiones de sesiones opacas locales y su contrato HTTP optativo."""

from __future__ import annotations

import hashlib

import pytest
from apps.api.app.local_staff_sessions import (
    COOKIE_NAME,
    LocalOpaqueStaffSessions,
    session_cookie_header,
)
from apps.api.app.main import create_app
from apps.api.app.staff_auth import StaffGrant, StaffPrincipal, StaffRole
from fastapi.testclient import TestClient

ROUTE = "/api/v1/staff/session"


def _principal(subject: str = "synthetic-user") -> StaffPrincipal:
    return StaffPrincipal(
        subject=subject,
        grants=(StaffGrant("alpha", "main", frozenset({StaffRole.READ_ORDERS})),),
    )


def _client(store: LocalOpaqueStaffSessions) -> TestClient:
    return TestClient(
        create_app(
            staff_session_reader=store,
            staff_published_scopes=frozenset({("alpha", "main"), ("ungranted", "main")}),
        )
    )


def test_cookie_session_is_opaque_and_server_scoped() -> None:
    store = LocalOpaqueStaffSessions(clock=lambda: 10.0)
    token = store.issue_for_trusted_server(_principal())
    assert len(token) >= 40
    assert token not in repr(store._sessions)
    assert hashlib.sha256(token.encode("ascii")).hexdigest() in store._sessions

    client = _client(store)
    assert client.get(ROUTE).status_code == 401
    client.cookies.set(COOKIE_NAME, token, path="/")
    response = client.get(ROUTE)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json() == {
        "subject": "synthetic-user",
        "scopes": [{"business_slug": "alpha", "location_slug": "main", "roles": ["read_orders"]}],
    }
    assert token not in response.text
    assert "ungranted" not in response.text


def test_expiration_and_revocation_fail_closed() -> None:
    now = [10.0]
    store = LocalOpaqueStaffSessions(lifetime_seconds=30, clock=lambda: now[0])
    token = store.issue_for_trusted_server(_principal())
    client = _client(store)
    client.cookies.set(COOKIE_NAME, token, path="/")
    assert client.get(ROUTE).status_code == 200
    now[0] = 40.0
    assert client.get(ROUTE).status_code == 401
    assert token not in repr(store._sessions)
    new_token = store.issue_for_trusted_server(_principal())
    client.cookies.set(COOKIE_NAME, new_token, path="/")
    assert client.get(ROUTE).status_code == 200
    store.revoke(new_token)
    assert client.get(ROUTE).status_code == 401


def test_forged_header_bearer_and_cookie_are_rejected() -> None:
    store = LocalOpaqueStaffSessions(clock=lambda: 10.0)
    client = _client(store)
    result = client.get(
        ROUTE,
        headers={"X-User": "admin", "X-Roles": "read_orders", "Authorization": "Bearer fake"},
        cookies={COOKIE_NAME: "Z" * 43},
    )
    assert result.status_code == 401


def test_capacity_is_bounded_and_recovers_after_expiration() -> None:
    now = [0.0]
    store = LocalOpaqueStaffSessions(
        lifetime_seconds=10, max_sessions=1, clock=lambda: now[0]
    )
    store.issue_for_trusted_server(_principal())
    with pytest.raises(RuntimeError, match="capacity"):
        store.issue_for_trusted_server(_principal())
    now[0] = 10.0
    store.issue_for_trusted_server(_principal())


def test_cookie_transport_attributes_and_invalid_configurations() -> None:
    header = session_cookie_header("a" * 43, max_age=300)
    assert header.startswith(f"{COOKIE_NAME}=")
    assert "Secure" in header
    assert "HttpOnly" in header
    assert "SameSite=Strict" in header
    assert "Path=/" in header
    for kwargs in (
        {"lifetime_seconds": 0},
        {"lifetime_seconds": float("nan")},
        {"max_sessions": 0},
        {"max_sessions": True},
    ):
        with pytest.raises(ValueError):
            LocalOpaqueStaffSessions(**kwargs)
    with pytest.raises(ValueError):
        session_cookie_header("test", max_age=0)


def test_default_app_does_not_activate_lab_sessions() -> None:
    assert TestClient(create_app()).get(ROUTE).status_code == 503
