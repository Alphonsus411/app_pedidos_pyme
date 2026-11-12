"""F3.11: HTTP + SQLite transaccional, aislamiento y replays de staff."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from apps.api.app.local_staff_sessions import COOKIE_NAME, LocalOpaqueStaffSessions
from apps.api.app.main import create_app
from apps.api.app.public_catalog import PublicCatalogScope
from apps.api.app.public_orders import PublicOrderItem, SqlitePublicOrders
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
    path: str, *, allow_transitions: bool = True
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


@pytest.mark.parametrize("same_key", [True, False])
def test_simultaneous_staff_transitions_are_serialized_and_idempotent(
    tmp_path, same_key: bool
) -> None:
    """Dos conexiones SQLite llegan a la misma orden en paralelo."""
    path = str(tmp_path / "concurrent-order.db")
    client, sessions, csrf, first_id, second_id = _setup(path)
    token = _authenticate(client, sessions, roles=frozenset({StaffRole.MANAGE_ORDERS}))
    route = f"{FIRST_ROUTE}/{first_id}/transitions"
    before = _counts(path)
    barrier = Barrier(2, timeout=10)

    def attempt(index: int) -> int:
        headers = _headers(
            csrf, token, key="concurrent-0001" if same_key else f"concurrent-000{index + 1}"
        )
        with TestClient(client.app) as concurrent_client:
            concurrent_client.cookies.set(COOKIE_NAME, token, path="/")
            barrier.wait()
            result = concurrent_client.post(route, json={"action": "validate"}, headers=headers)
            return result.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(attempt, index) for index in range(2)]
        codes = [future.result(timeout=15) for future in futures]

    assert codes.count(200) >= 1
    assert all(code in (200, 409) for code in codes)
    if not same_key:
        assert sorted(codes) == [200, 409]
    assert _status(path, first_id) == "validated"
    assert _status(path, second_id) == "draft"
    assert _counts(path) == (before[0] + 1, before[1] + 1)

    # Un replay, también después de la carrera, no vuelve a escribir.
    assert (
        client.post(
            route,
            json={"action": "validate"},
            headers=_headers(csrf, token, key="concurrent-0001"),
        ).status_code
        == 200
    )
    assert _counts(path) == (before[0] + 1, before[1] + 1)


def test_parallel_transitions_different_tenants_preserve_isolation(tmp_path) -> None:
    """Dos negocios pueden cambiar pedidos propios sin cruzar sus efectos."""
    path = str(tmp_path / "parallel-businesses.db")
    client, sessions, csrf, first_id, second_id = _setup(path)
    first_token = _authenticate(
        client, sessions, roles=frozenset({StaffRole.MANAGE_ORDERS})
    )
    second_token = sessions.issue_for_trusted_server(
        StaffPrincipal(
            subject="second-operator",
            grants=(StaffGrant("second", "main", frozenset({StaffRole.MANAGE_ORDERS})),),
        )
    )
    before = _counts(path)
    barrier = Barrier(2, timeout=10)

    def change(business: str, token: str, order_id: str) -> int:
        with TestClient(client.app) as worker_client:
            worker_client.cookies.set(COOKIE_NAME, token, path="/")
            barrier.wait()
            response = worker_client.post(
                f"/api/v1/staff/businesses/{business}/locations/main/orders/{order_id}/transitions",
                json={"action": "validate"},
                headers=_headers(csrf, token, business=business, key=f"{business}-parallel-0001"),
            )
            return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(change, "first", first_token, first_id),
            executor.submit(change, "second", second_token, second_id),
        ]
        codes = [future.result(timeout=15) for future in futures]

    assert codes == [200, 200]
    assert _status(path, first_id) == "validated"
    assert _status(path, second_id) == "validated"
    assert _counts(path) == (before[0] + 2, before[1] + 2)
