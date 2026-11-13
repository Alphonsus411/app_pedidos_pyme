"""F3.16: subprocess-only synthetic crash scenarios; never import in production."""

from __future__ import annotations

import os
import sqlite3
import sys
from collections.abc import Callable

from apps.api.app.local_staff_sessions import COOKIE_NAME, LocalOpaqueStaffSessions
from apps.api.app.main import create_app
from apps.api.app.public_catalog import PublicCatalogScope
from apps.api.app.staff_auth import StaffGrant, StaffPrincipal, StaffRole
from apps.api.app.staff_csrf import StaffMutationCsrf
from apps.api.app.staff_order_transitions import SqliteStaffOrderTransitions
from fastapi.testclient import TestClient

from universal_business.domain.orders.entities import Order
from universal_business.domain.orders.value_objects import OrderStatus
from universal_business.domain.shared.value_objects.ids import BusinessId, LocationId, TenantId


class LaboratoryPolicy:
    def approve(self, *, order: Order, target: OrderStatus) -> bool:
        del order, target
        return True


def _transition_after_commit(path: str, order_id: str, key: str) -> None:
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT tenant_id, business_id, location_id FROM orders WHERE id=?",
            (order_id,),
        ).fetchone()
    if row is None:
        raise RuntimeError("Synthetic order missing")

    scopes = {
        ("first", "main"): PublicCatalogScope(
            tenant_id=TenantId.from_raw(row[0]),
            business_id=BusinessId.from_raw(row[1]),
            location_id=LocationId.from_raw(row[2]),
        )
    }
    sessions = LocalOpaqueStaffSessions()
    csrf = StaffMutationCsrf(secret=b"s" * 32, allowed_origins=["https://panel.example.test"])
    token = sessions.issue_for_trusted_server(
        StaffPrincipal(
            subject="process-operator",
            grants=(StaffGrant("first", "main", frozenset({StaffRole.MANAGE_ORDERS})),),
        )
    )
    app = create_app(
        staff_session_reader=sessions,
        staff_published_scopes=frozenset(scopes),
        staff_mutation_csrf=csrf,
        staff_order_transitions=SqliteStaffOrderTransitions(
            connect=lambda: sqlite3.connect(path),
            scopes=scopes,
            policy=LaboratoryPolicy(),
        ),
    )
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, token, path="/")
        response = client.post(
            f"/api/v1/staff/businesses/first/locations/main/orders/{order_id}/transitions",
            json={"action": "validate"},
            headers={
                "Origin": "https://panel.example.test",
                "Idempotency-Key": key,
                "X-CSRF-Token": csrf.issue_for_trusted_server(
                    session_token=token,
                    business_slug="first",
                    location_slug="main",
                    action="validate",
                ),
            },
        )
        if response.status_code != 200:
            raise RuntimeError(f"Unexpected response code: {response.status_code}")
    # Client never receives the successful response; the child is terminated
    # only after the full HTTP handler/SQLite commit has returned successfully.
    os._exit(18)


def _crash_before_commit(path: str, order_id: str) -> None:
    connection = sqlite3.connect(path)
    connection.execute("BEGIN IMMEDIATE")
    result = connection.execute(
        "UPDATE orders SET status='validated' WHERE id=? AND status='draft'", (order_id,)
    )
    if result.rowcount != 1:
        raise RuntimeError("Synthetic order was not draft")
    # Kill a real SQLite writer process with an uncommitted transaction.
    # This is not an injected crash into the domain transition handler.
    os._exit(17)


def main() -> None:
    if len(sys.argv) != 5:
        raise SystemExit(2)
    _, mode, path, order_id, key = sys.argv
    scenarios: dict[str, Callable[[], None]] = {
        "before": lambda: _crash_before_commit(path, order_id),
        "after": lambda: _transition_after_commit(path, order_id, key),
    }
    if mode not in scenarios:
        raise SystemExit(2)
    scenarios[mode]()


if __name__ == "__main__":
    main()
