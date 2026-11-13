"""F3.11: HTTP + SQLite transaccional, aislamiento y replays de staff."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

import pytest
from apps.api.app.local_staff_sessions import COOKIE_NAME, LocalOpaqueStaffSessions
from apps.api.app.main import create_app
from apps.api.app.public_catalog import PublicCatalogScope
from apps.api.app.public_orders import PublicOrderItem, SqlitePublicOrders
from apps.api.app.staff_audit import StaffAccessAuditEvent, StaffAuditSink
from apps.api.app.staff_auth import StaffGrant, StaffPrincipal, StaffRole
from apps.api.app.staff_csrf import StaffMutationCsrf
from apps.api.app.staff_order_transitions import SqliteStaffOrderTransitions
from fastapi.testclient import TestClient

from universal_business.domain.business.entities import Location
from universal_business.domain.business.value_objects import Address, LocationStatus, OperatingHours
from universal_business.domain.catalog.entities import Offering
from universal_business.domain.catalog.value_objects import CatalogItemStatus
from universal_business.domain.orders.entities import Order
from universal_business.domain.orders.value_objects import OrderStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    OfferingId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money
from universal_business.infrastructure.sqlite_locations import SqliteLocationRepository
from universal_business.infrastructure.sqlite_offerings import SqliteOfferingRepository
from universal_business.infrastructure.sqlite_schema import initialize_sqlite_schema
from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork

ORIGIN = "https://panel.example.test"
FIRST_ROUTE = "/api/v1/staff/businesses/first/locations/main/orders"
SECOND_ROUTE = "/api/v1/staff/businesses/second/locations/main/orders"


class ApproveLaboratoryTransitions:
    def __init__(self, *, allowed: bool = True) -> None:
        self.allowed = allowed

    def approve(self, *, order: Order, target: OrderStatus) -> bool:
        del order, target
        return self.allowed


def _setup(
    path: str, *, allow_transitions: bool = True, audit_sink: StaffAuditSink | None = None
) -> tuple[TestClient, LocalOpaqueStaffSessions, StaffMutationCsrf, str, str]:
    scopes = {}
    offerings = {}
    with sqlite3.connect(path) as connection:
        initialize_sqlite_schema(connection)
        with SqliteUnitOfWork(connection) as uow:
            for slug in ("first", "second"):
                tenant, business, location, offering = (
                    TenantId.generate(),
                    BusinessId.generate(),
                    LocationId.generate(),
                    OfferingId.generate(),
                )
                scopes[(slug, "main")] = PublicCatalogScope(
                    tenant_id=tenant, business_id=business, location_id=location
                )
                offerings[slug] = str(offering)
                SqliteLocationRepository(connection).save(
                    Location(
                        id=location,
                        tenant_id=tenant,
                        business_id=business,
                        name="Synthetic location",
                        address=Address(country_code="ES"),
                        timezone="UTC",
                        operating_hours=OperatingHours(),
                        status=LocationStatus.OPEN,
                    )
                )
                SqliteOfferingRepository(connection).save(
                    Offering(
                        id=offering,
                        tenant_id=tenant,
                        business_id=business,
                        name="Synthetic item",
                        description="Laboratory-only",
                        status=CatalogItemStatus.ACTIVE,
                        base_price=Money("12.50", "EUR"),
                        location_ids=frozenset({location}),
                    )
                )
            uow.commit()
    drafts = SqlitePublicOrders(connect=lambda: sqlite3.connect(path), scopes=scopes)
    first_id = drafts.create_draft(
        business_slug="first",
        location_slug="main",
        idempotency_key="staff-lab-first",
        items=[PublicOrderItem(offering_id=offerings["first"], quantity=Decimal("1"))],
    )["id"]
    second_id = drafts.create_draft(
        business_slug="second",
        location_slug="main",
        idempotency_key="staff-lab-second",
        items=[PublicOrderItem(offering_id=offerings["second"], quantity=Decimal("1"))],
    )["id"]
    sessions = LocalOpaqueStaffSessions()
    csrf = StaffMutationCsrf(secret=b"s" * 32, allowed_origins=[ORIGIN])
    app = create_app(
        staff_audit_sink=audit_sink,
        staff_session_reader=sessions,
        staff_published_scopes=frozenset(scopes),
        staff_mutation_csrf=csrf,
        staff_order_transitions=SqliteStaffOrderTransitions(
            connect=lambda: sqlite3.connect(path),
            scopes=scopes,
            policy=ApproveLaboratoryTransitions(allowed=allow_transitions),
        ),
    )
    return TestClient(app), sessions, csrf, str(first_id), str(second_id)


def _authenticate(
    client: TestClient,
    sessions: LocalOpaqueStaffSessions,
    *,
    roles: frozenset[StaffRole],
    business: str = "first",
) -> str:
    token = sessions.issue_for_trusted_server(
        StaffPrincipal(
            subject="operator",
            grants=(StaffGrant(business, "main", roles),),
        )
    )
    client.cookies.set(COOKIE_NAME, token, path="/")
    return token


def _headers(
    csrf: StaffMutationCsrf,
    token: str,
    *,
    business: str = "first",
    action: str = "validate",
    key: str = "transition-0001",
) -> dict[str, str]:
    return {
        "Origin": ORIGIN,
        "X-CSRF-Token": csrf.issue_for_trusted_server(
            session_token=token,
            business_slug=business,
            location_slug="main",
            action=action,
        ),
        "Idempotency-Key": key,
    }


def _counts(path: str) -> tuple[int, int]:
    with sqlite3.connect(path) as connection:
        return (
            connection.execute("SELECT COUNT(*) FROM idempotency").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM transactional_outbox").fetchone()[0],
        )


def _status(path: str, order_id: str) -> str:
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT status FROM orders WHERE id=?", (order_id,)).fetchone()[0]


def test_successful_transition_is_atomic_and_replay_has_no_extra_events(tmp_path) -> None:
    path = str(tmp_path / "orders.db")
    client, sessions, csrf, first_id, _ = _setup(path)
    token = _authenticate(client, sessions, roles=frozenset({StaffRole.MANAGE_ORDERS}))
    route = f"{FIRST_ROUTE}/{first_id}/transitions"
    before = _counts(path)
    created = client.post(route, json={"action": "validate"}, headers=_headers(csrf, token))
    assert created.status_code == 200
    assert created.json() == {"id": first_id, "status": "validated"}
    assert _status(path, first_id) == "validated"
    after = _counts(path)
    assert after == (before[0] + 1, before[1] + 1)
    replay = client.post(route, json={"action": "validate"}, headers=_headers(csrf, token))
    assert replay.status_code == 200
    assert replay.json() == created.json()
    assert _counts(path) == after


@pytest.mark.parametrize(
    "case",
    [
        "no-session",
        "read-only",
        "other-business",
        "cross-order",
        "no-origin",
        "bad-csrf",
        "no-csrf",
        "changed-action",
        "invalid-action",
        "no-idempotency",
    ],
)
def test_rejected_request_does_not_write(tmp_path, case: str) -> None:
    path = str(tmp_path / "reject.db")
    client, sessions, csrf, first_id, second_id = _setup(path)
    token = _authenticate(
        client,
        sessions,
        roles=frozenset({StaffRole.READ_ORDERS})
        if case == "read-only"
        else frozenset({StaffRole.MANAGE_ORDERS}),
    )
    route = f"{FIRST_ROUTE}/{second_id if case == 'cross-order' else first_id}/transitions"
    if case == "other-business":
        route = f"{SECOND_ROUTE}/{second_id}/transitions"
    headers = _headers(csrf, token)
    if case == "no-session":
        client.cookies.clear()
    elif case == "no-origin":
        headers.pop("Origin")
    elif case == "bad-csrf":
        headers["X-CSRF-Token"] = "Z" * 43
    elif case == "no-csrf":
        headers.pop("X-CSRF-Token")
    elif case == "changed-action":
        headers["X-CSRF-Token"] = csrf.issue_for_trusted_server(
            session_token=token, business_slug="first", location_slug="main", action="confirm"
        )
    elif case == "no-idempotency":
        headers.pop("Idempotency-Key")
    before = _counts(path)
    result = client.post(
        route,
        json={"action": "not-an-action" if case == "invalid-action" else "validate"},
        headers=headers,
    )
    expected = (
        401
        if case == "no-session"
        else 422
        if case in {"invalid-action", "no-idempotency"}
        else 404
        if case == "cross-order"
        else 403
    )
    assert result.status_code == expected
    assert _counts(path) == before
    assert _status(path, first_id) == "draft"
    assert _status(path, second_id) == "draft"


def test_repeated_action_new_key_is_conflict_and_no_duplicate_event(tmp_path) -> None:
    path = str(tmp_path / "repeat.db")
    client, sessions, csrf, first_id, _ = _setup(path)
    token = _authenticate(client, sessions, roles=frozenset({StaffRole.MANAGE_ORDERS}))
    route = f"{FIRST_ROUTE}/{first_id}/transitions"
    assert (
        client.post(route, json={"action": "validate"}, headers=_headers(csrf, token)).status_code
        == 200
    )
    counts = _counts(path)
    conflict = client.post(
        route,
        json={"action": "validate"},
        headers=_headers(csrf, token, key="transition-0002"),
    )
    assert conflict.status_code == 409
    assert _counts(path) == counts


def test_config_missing_is_503_and_no_static_bearer_fallback() -> None:
    client = TestClient(create_app())
    route = f"{FIRST_ROUTE}/00000000-0000-4000-8000-000000000099/transitions"
    result = client.post(
        route,
        json={"action": "validate"},
        headers={"Idempotency-Key": "transition-0001", "Authorization": "Bearer test"},
    )
    assert result.status_code == 503


def test_policy_denial_rolls_back_idempotency_and_outbox(tmp_path) -> None:
    path = str(tmp_path / "policy-denial.db")
    client, sessions, csrf, order_id, _ = _setup(path, allow_transitions=False)
    token = _authenticate(client, sessions, roles=frozenset({StaffRole.MANAGE_ORDERS}))
    route = f"{FIRST_ROUTE}/{order_id}/transitions"
    before = _counts(path)
    denied = client.post(route, json={"action": "validate"}, headers=_headers(csrf, token))
    assert denied.status_code == 409
    assert _counts(path) == before
    assert _status(path, order_id) == "draft"


def test_revoked_session_has_no_bearer_fallback_or_side_effects(tmp_path) -> None:
    path = str(tmp_path / "revoked.db")
    client, sessions, csrf, first_id, _ = _setup(path)
    token = _authenticate(client, sessions, roles=frozenset({StaffRole.MANAGE_ORDERS}))
    headers = _headers(csrf, token)
    headers["Authorization"] = "Bearer development-staff-token"
    before = _counts(path)
    sessions.revoke(token)
    result = client.post(
        f"{FIRST_ROUTE}/{first_id}/transitions",
        json={"action": "validate"},
        headers=headers,
    )
    assert result.status_code == 401
    assert _status(path, first_id) == "draft"
    assert _counts(path) == before


def test_transition_audit_records_safe_outcomes_and_replays(tmp_path) -> None:
    class Sink:
        def __init__(self) -> None:
            self.events: list[StaffAccessAuditEvent] = []

        def record(self, event: StaffAccessAuditEvent) -> None:
            self.events.append(event)

    sink = Sink()
    path = str(tmp_path / "audit-transitions.db")
    client, sessions, csrf, first_id, second_id = _setup(path, audit_sink=sink)
    route = f"{FIRST_ROUTE}/{first_id}/transitions"
    unauthenticated = client.post(
        route, json={"action": "validate"}, headers={"Idempotency-Key": "transition-0001"}
    )
    token = _authenticate(client, sessions, roles=frozenset({StaffRole.READ_ORDERS}))
    forbidden = client.post(route, json={"action": "validate"}, headers=_headers(csrf, token))
    token = _authenticate(client, sessions, roles=frozenset({StaffRole.MANAGE_ORDERS}))
    csrf_denied = client.post(
        route,
        json={"action": "validate"},
        headers={**_headers(csrf, token), "X-CSRF-Token": "Z" * 43},
    )
    foreign = client.post(
        f"{FIRST_ROUTE}/{second_id}/transitions",
        json={"action": "validate"},
        headers=_headers(csrf, token),
    )
    success = client.post(route, json={"action": "validate"}, headers=_headers(csrf, token))
    replay = client.post(route, json={"action": "validate"}, headers=_headers(csrf, token))
    conflict = client.post(
        route, json={"action": "validate"}, headers=_headers(csrf, token, key="transition-0002")
    )
    responses = [unauthenticated, forbidden, csrf_denied, foreign, success, replay, conflict]
    assert [r.status_code for r in responses] == [401, 403, 403, 404, 200, 200, 409]
    assert [e.status_code for e in sink.events] == [401, 403, 403, 404, 200, 200, 409]
    assert [e.subject for e in sink.events] == [
        None, "operator", "operator", "operator", "operator", "operator", "operator"
    ]
    assert all(e.action == "transition_order" for e in sink.events)
    for event, response in zip(sink.events, responses, strict=True):
        assert event.request_id == response.headers["X-Request-ID"]
        assert event.business_slug == "first" and event.location_slug == "main"
        serialized = str(event)
        for secret in (token, first_id, second_id, "transition-0001", "transition-0002"):
            assert secret not in serialized
        assert not hasattr(event, "csrf_token")
        assert not hasattr(event, "idempotency_key")
        assert not hasattr(event, "order_id")


def test_transition_audit_sink_failure_does_not_mask_result(tmp_path) -> None:
    class FailingSink:
        def record(self, event: StaffAccessAuditEvent) -> None:
            raise RuntimeError("synthetic sink failure")

    client, sessions, csrf, first_id, _ = _setup(
        str(tmp_path / "audit-failure.db"), audit_sink=FailingSink()
    )
    route = f"{FIRST_ROUTE}/{first_id}/transitions"
    assert client.post(
        route, json={"action": "validate"}, headers={"Idempotency-Key": "transition-0001"}
    ).status_code == 401
    token = _authenticate(client, sessions, roles=frozenset({StaffRole.MANAGE_ORDERS}))
    assert client.post(
        route, json={"action": "validate"}, headers=_headers(csrf, token)
    ).status_code == 200
