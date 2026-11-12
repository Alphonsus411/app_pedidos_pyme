"""Contrato F3 de sesión de servidor y descubrimiento de scopes permitidos."""

from __future__ import annotations

from apps.api.app.main import create_app
from apps.api.app.staff_auth import AuthenticationRequired, StaffGrant, StaffPrincipal, StaffRole
from fastapi.testclient import TestClient

ROUTE = "/api/v1/staff/session"


class DemoSessionReader:
    def __init__(self, principal: StaffPrincipal | None) -> None:
        self.principal = principal
        self.called = 0

    def current_principal(self, request) -> StaffPrincipal:
        self.called += 1
        if self.principal is None:
            raise AuthenticationRequired
        return self.principal


def _principal() -> StaffPrincipal:
    return StaffPrincipal(
        subject="synthetic-operator",
        grants=(
            StaffGrant("alpha", "main", frozenset({StaffRole.READ_ORDERS})),
            StaffGrant("beta", "branch", frozenset({StaffRole.READ_ORDERS})),
            StaffGrant("alpha", "main", frozenset({StaffRole.READ_ORDERS})),
            StaffGrant("orphan", "hidden", frozenset({StaffRole.READ_ORDERS})),
        ),
    )


def test_session_is_unavailable_without_provider() -> None:
    client = TestClient(create_app())
    response = client.get(ROUTE)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_session_denies_anonymous_and_never_returns_grants() -> None:
    reader = DemoSessionReader(None)
    client = TestClient(
        create_app(
            staff_session_reader=reader,
            staff_published_scopes=frozenset({("alpha", "main")}),
        )
    )
    response = client.get(ROUTE)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
    assert reader.called == 1


def test_session_lists_only_published_authorized_scopes() -> None:
    reader = DemoSessionReader(_principal())
    client = TestClient(
        create_app(
            staff_session_reader=reader,
            staff_published_scopes=frozenset(
                {("alpha", "main"), ("beta", "branch"), ("third", "main")}
            ),
        )
    )
    response = client.get(ROUTE)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json() == {
        "subject": "synthetic-operator",
        "scopes": [
            {"business_slug": "alpha", "location_slug": "main", "roles": ["read_orders"]},
            {"business_slug": "beta", "location_slug": "branch", "roles": ["read_orders"]},
        ],
    }
    assert "token" not in response.text.lower()
    assert "orphan" not in response.text
    assert "third" not in response.text


def test_session_empty_scopes_does_not_grant_access() -> None:
    client = TestClient(
        create_app(
            staff_session_reader=DemoSessionReader(_principal()),
            staff_published_scopes=frozenset(),
        )
    )
    response = client.get(ROUTE)
    assert response.status_code == 200
    assert response.json()["scopes"] == []


def test_session_is_not_derived_from_browser_identity_headers() -> None:
    client = TestClient(
        create_app(
            staff_session_reader=DemoSessionReader(None),
            staff_published_scopes=frozenset({("alpha", "main")}),
        )
    )
    response = client.get(
        ROUTE,
        headers={
            "X-User-Id": "synthetic-operator",
            "X-Roles": "read_orders",
            "X-Business-Slug": "alpha",
            "Authorization": "Bearer arbitrary",
        },
    )
    assert response.status_code == 401
