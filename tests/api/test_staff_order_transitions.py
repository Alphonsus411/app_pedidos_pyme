"""F3.11: HTTP + SQLite transaccional, aislamiento y replays de staff."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from threading import Barrier

import pytest
from apps.api.app.local_staff_sessions import COOKIE_NAME, LocalOpaqueStaffSessions
from apps.api.app.main import create_app
from apps.api.app.public_catalog import PublicCatalogScope
from apps.api.app.public_orders import PublicOrderItem, SqlitePublicOrders
from apps.api.app.staff_audit import StaffAccessAuditEvent, StaffAuditSink
from apps.api.app.staff_auth import StaffGrant, StaffPrincipal, StaffRole
from apps.api.app.staff_csrf import StaffMutationCsrf
from apps.api.app.staff_order_transitions import SqliteStaffOrderTransitions
from apps.api.app.staff_orders import SqliteStaffOrders
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
    path: str,
    *,
    allow_transitions: bool = True,
    audit_sink: StaffAuditSink | None = None,
    transition_timeout: float = 5.0,
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
        staff_orders=SqliteStaffOrders(connect=lambda: sqlite3.connect(path), scopes=scopes),
        staff_order_transitions=SqliteStaffOrderTransitions(
            connect=lambda: sqlite3.connect(path, timeout=transition_timeout),
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
    assert sink.events[0].subject is None
    assert all(event.subject == "operator" for event in sink.events[1:])
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
    unauthenticated = client.post(
        route, json={"action": "validate"}, headers={"Idempotency-Key": "transition-0001"}
    )
    assert unauthenticated.status_code == 401
    token = _authenticate(client, sessions, roles=frozenset({StaffRole.MANAGE_ORDERS}))
    accepted = client.post(route, json={"action": "validate"}, headers=_headers(csrf, token))
    assert accepted.status_code == 200


@pytest.mark.parametrize("same_key", [True, False], ids=["replay", "different-keys"])
def test_parallel_transition_same_order_is_atomic(tmp_path, same_key: bool) -> None:
    """Two independent HTTP clients race for one SQLite order."""
    path = str(tmp_path / "parallel-order.db")
    base_client, sessions, csrf, order_id, _ = _setup(path)
    token = sessions.issue_for_trusted_server(
        StaffPrincipal(
            subject="operator",
            grants=(StaffGrant("first", "main", frozenset({StaffRole.MANAGE_ORDERS})),),
        )
    )
    route = f"{FIRST_ROUTE}/{order_id}/transitions"
    initial = _counts(path)
    gate = Barrier(2)

    def request_transition(index: int) -> tuple[int, dict[str, str]]:
        # Each request gets its own client and cookie jar. The shared app uses
        # separate SQLite connections per request, not a shared connection.
        with TestClient(base_client.app) as client:
            client.cookies.set(COOKIE_NAME, token, path="/")
            key = "parallel-key-001" if same_key else f"parallel-key-00{index + 1}"
            headers = _headers(csrf, token, key=key)
            gate.wait(timeout=10)
            response = client.post(route, json={"action": "validate"}, headers=headers)
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(request_transition, index) for index in range(2)]
        outcomes = [future.result(timeout=20) for future in futures]

    statuses = sorted(status for status, _ in outcomes)
    assert statuses == ([200, 200] if same_key else [200, 409])
    assert all(
        payload == {"id": order_id, "status": "validated"}
        for status, payload in outcomes
        if status == 200
    )
    assert _status(path, order_id) == "validated"
    assert _counts(path) == (initial[0] + 1, initial[1] + 1)

    # Preserve PR #109's additional post-race verification: the winning
    # idempotency key must replay; the losing key must remain rejected.
    base_client.cookies.set(COOKIE_NAME, token, path="/")
    for index, (status, _) in enumerate(outcomes):
        key = "parallel-key-001" if same_key else f"parallel-key-00{index + 1}"
        replay = base_client.post(
            route, json={"action": "validate"}, headers=_headers(csrf, token, key=key)
        )
        assert replay.status_code == (200 if same_key or status == 200 else 409)
    assert _counts(path) == (initial[0] + 1, initial[1] + 1)


def test_parallel_transitions_remain_scoped_to_separate_businesses(tmp_path) -> None:
    path = str(tmp_path / "parallel-businesses.db")
    base_client, sessions, csrf, first_id, second_id = _setup(path)
    gate = Barrier(2)
    before = _counts(path)

    def transition(business: str, order_id: str) -> tuple[int, dict[str, str]]:
        token = sessions.issue_for_trusted_server(
            StaffPrincipal(
                subject=f"operator-{business}",
                grants=(StaffGrant(business, "main", frozenset({StaffRole.MANAGE_ORDERS})),),
            )
        )
        route = f"/api/v1/staff/businesses/{business}/locations/main/orders/{order_id}/transitions"
        with TestClient(base_client.app) as client:
            client.cookies.set(COOKIE_NAME, token, path="/")
            headers = _headers(csrf, token, business=business, key=f"parallel-{business}-001")
            gate.wait(timeout=10)
            response = client.post(route, json={"action": "validate"}, headers=headers)
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(transition, "first", first_id)
        second = pool.submit(transition, "second", second_id)
        responses = [first.result(timeout=20), second.result(timeout=20)]

    assert responses == [
        (200, {"id": first_id, "status": "validated"}),
        (200, {"id": second_id, "status": "validated"}),
    ]
    assert _status(path, first_id) == _status(path, second_id) == "validated"
    assert _counts(path) == (before[0] + 2, before[1] + 2)


def test_sqlite_writer_timeout_is_503_without_writes_and_recovers(tmp_path) -> None:
    path = str(tmp_path / "busy-transition.db")
    client, sessions, csrf, order_id, _ = _setup(path, transition_timeout=0.05)
    token = _authenticate(client, sessions, roles=frozenset({StaffRole.MANAGE_ORDERS}))
    route = f"{FIRST_ROUTE}/{order_id}/transitions"
    headers = _headers(csrf, token, key="busy-transition-0001")
    before = _counts(path)

    # Hold a separate writer transaction past the request's SQLite timeout.
    with sqlite3.connect(path) as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        blocked = client.post(route, json={"action": "validate"}, headers=headers)
        assert blocked.status_code == 503
        assert blocked.headers["Retry-After"] == "1"
        assert blocked.headers["X-Request-ID"]
        assert blocked.json()["error"]["code"] == "service_unavailable"
        assert "locked" not in blocked.text.lower()
        blocker.rollback()

    assert _status(path, order_id) == "draft"
    assert _counts(path) == before

    # Retry with the exact same request key, not a fresh mutation key.
    retry = client.post(route, json={"action": "validate"}, headers=headers)
    assert retry.status_code == 200
    assert retry.json() == {"id": order_id, "status": "validated"}
    assert _counts(path) == (before[0] + 1, before[1] + 1)
    replay = client.post(route, json={"action": "validate"}, headers=headers)
    assert replay.status_code == 200
    assert _counts(path) == (before[0] + 1, before[1] + 1)


def test_sqlite_contention_does_not_leak_exception_into_staff_audit(tmp_path) -> None:
    class Sink:
        def __init__(self) -> None:
            self.events: list[StaffAccessAuditEvent] = []

        def record(self, event: StaffAccessAuditEvent) -> None:
            self.events.append(event)

    path = str(tmp_path / "busy-audit.db")
    sink = Sink()
    client, sessions, csrf, order_id, _ = _setup(path, audit_sink=sink, transition_timeout=0.05)
    token = _authenticate(client, sessions, roles=frozenset({StaffRole.MANAGE_ORDERS}))
    route = f"{FIRST_ROUTE}/{order_id}/transitions"
    with sqlite3.connect(path) as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        result = client.post(route, json={"action": "validate"}, headers=_headers(csrf, token))
        blocker.rollback()

    assert result.status_code == 503
    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.action == "transition_order"
    assert event.status_code == 503
    assert event.request_id == result.headers["X-Request-ID"]
    assert event.subject == "operator"
    assert order_id not in str(event)
    assert token not in str(event)
    assert _status(path, order_id) == "draft"


def test_lost_transition_response_reconciles_by_read_and_same_key(tmp_path) -> None:
    """A client discards the 200 after the database commit, then reconnects."""
    path = str(tmp_path / "response-lost.db")
    base_client, sessions, csrf, order_id, foreign_id = _setup(path)
    token = sessions.issue_for_trusted_server(
        StaffPrincipal(
            subject="reconciling-operator",
            grants=(
                StaffGrant(
                    "first",
                    "main",
                    frozenset({StaffRole.READ_ORDERS, StaffRole.MANAGE_ORDERS}),
                ),
            ),
        )
    )
    route = f"{FIRST_ROUTE}/{order_id}/transitions"
    headers = _headers(csrf, token, key="reconcile-0001")
    before = _counts(path)

    # The HTTP response is deliberately discarded AFTER the real FastAPI
    # handler commits. This is not a TCP disconnect or a crash injection.
    with TestClient(base_client.app) as original:
        original.cookies.set(COOKIE_NAME, token, path="/")
        original.post(route, json={"action": "validate"}, headers=headers)

    assert _status(path, order_id) == "validated"
    committed = _counts(path)
    assert committed == (before[0] + 1, before[1] + 1)

    with TestClient(base_client.app) as restored:
        restored.cookies.set(COOKIE_NAME, token, path="/")
        detail = restored.get(f"{FIRST_ROUTE}/{order_id}")
        assert detail.status_code == 200
        assert detail.json()["status"] == "validated"
        # Read-only state alone does NOT prove that this request committed.
        replay = restored.post(route, json={"action": "validate"}, headers=headers)
        assert replay.status_code == 200
        assert replay.json() == {"id": order_id, "status": "validated"}
        assert _counts(path) == committed
        # A new idempotency key must not claim the already-applied transition.
        different_key = restored.post(
            route, json={"action": "validate"}, headers=_headers(csrf, token, key="reconcile-0002")
        )
        assert different_key.status_code == 409
        assert _counts(path) == committed
        # The same operator cannot reconcile a foreign resource.
        foreign = restored.get(f"{FIRST_ROUTE}/{foreign_id}")
        assert foreign.status_code == 404


def test_reconciliation_requires_read_grant_and_valid_session(tmp_path) -> None:
    path = str(tmp_path / "reconcile-permissions.db")
    client, sessions, csrf, order_id, _ = _setup(path)
    token = _authenticate(client, sessions, roles=frozenset({StaffRole.MANAGE_ORDERS}))
    route = f"{FIRST_ROUTE}/{order_id}/transitions"
    headers = _headers(csrf, token, key="reconcile-grant-0001")
    accepted = client.post(route, json={"action": "validate"}, headers=headers)
    assert accepted.status_code == 200
    committed = _counts(path)

    # manage_orders alone must not implicitly allow read_orders.
    assert client.get(f"{FIRST_ROUTE}/{order_id}").status_code == 403
    replay = client.post(route, json={"action": "validate"}, headers=headers)
    assert replay.status_code == 200
    assert _counts(path) == committed

    sessions.revoke(token)
    assert client.get(f"{FIRST_ROUTE}/{order_id}").status_code == 401
    assert client.post(route, json={"action": "validate"}, headers=headers).status_code == 401
    assert _counts(path) == committed


@pytest.mark.parametrize(
    ("mode", "expected_exit", "expected_status", "expected_delta"),
    [
        ("before", 17, "draft", 0),
        ("after", 18, "validated", 1),
    ],
)
def test_subprocess_interruption_reconciles_without_duplicate_outbox(
    tmp_path, mode: str, expected_exit: int, expected_status: str, expected_delta: int
) -> None:
    path = str(tmp_path / "interrupted.db")
    client, sessions, csrf, order_id, foreign_id = _setup(path)
    token = _authenticate(client, sessions, roles=frozenset({StaffRole.MANAGE_ORDERS}))
    route = f"{FIRST_ROUTE}/{order_id}/transitions"
    headers = _headers(csrf, token, key="interrupted-0001")
    before = _counts(path)

    worker = Path(__file__).with_name("staff_transition_process_worker.py")
    root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "PYTHONPATH": str(root) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    process = subprocess.run(
        [sys.executable, str(worker), mode, path, order_id, "interrupted-0001"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        cwd=root,
        env=env,
    )
    assert process.returncode == expected_exit, process.stderr
    # Verify durable SQLite state via a new connection, not child memory.
    assert _status(path, order_id) == expected_status
    assert _status(path, foreign_id) == "draft"
    assert _counts(path) == (
        before[0] + expected_delta,
        before[1] + expected_delta,
    )
    # On either side of the commit boundary, identical request/key must be
    # safe to retry and must produce exactly one committed transition/event.
    retry = client.post(route, json={"action": "validate"}, headers=headers)
    assert retry.status_code == 200
    assert retry.json() == {"id": order_id, "status": "validated"}
    assert _counts(path) == (before[0] + 1, before[1] + 1)
    replay = client.post(route, json={"action": "validate"}, headers=headers)
    assert replay.status_code == 200
    assert _counts(path) == (before[0] + 1, before[1] + 1)
