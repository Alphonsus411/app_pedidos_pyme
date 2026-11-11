"""Contrato HTTP de identidad técnica y aislamiento para pedidos de personal."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from decimal import Decimal

import pytest
from apps.api.app.main import create_app
from apps.api.app.public_catalog import PublicCatalogScope
from apps.api.app.public_orders import PublicOrderItem, SqlitePublicOrders
from apps.api.app.staff_audit import StaffAccessAuditEvent, StaffAuditSink
from apps.api.app.staff_auth import (
    AuthenticationRequired,
    StaffAuthenticator,
    StaffGrant,
    StaffPrincipal,
    StaffRole,
    StaticBearerAuthenticator,
)
from apps.api.app.staff_orders import SqliteStaffOrders
from fastapi.testclient import TestClient

from universal_business.domain.business.entities import Location
from universal_business.domain.business.value_objects import Address, LocationStatus, OperatingHours
from universal_business.domain.catalog.entities import Offering
from universal_business.domain.catalog.value_objects import CatalogItemStatus
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


def _staff_client(
    database_path: str,
    *,
    auth_wrapper: Callable[[StaticBearerAuthenticator], StaffAuthenticator] | None = None,
    audit_sink: StaffAuditSink | None = None,
) -> tuple[TestClient, str, str]:
    first_tenant, second_tenant = TenantId.generate(), TenantId.generate()
    first_business, second_business = BusinessId.generate(), BusinessId.generate()
    first_location, second_location = LocationId.generate(), LocationId.generate()
    first_offering, second_offering = OfferingId.generate(), OfferingId.generate()
    scopes = {
        ("first", "main"): PublicCatalogScope(
            tenant_id=first_tenant,
            business_id=first_business,
            location_id=first_location,
        ),
        ("second", "main"): PublicCatalogScope(
            tenant_id=second_tenant,
            business_id=second_business,
            location_id=second_location,
        ),
    }
    with sqlite3.connect(database_path) as connection:
        initialize_sqlite_schema(connection)
        with SqliteUnitOfWork(connection) as uow:
            locations = SqliteLocationRepository(connection)
            offerings = SqliteOfferingRepository(connection)
            for tenant, business, location, offering, name in (
                (first_tenant, first_business, first_location, first_offering, "First"),
                (second_tenant, second_business, second_location, second_offering, "Second"),
            ):
                locations.save(
                    Location(
                        id=location,
                        tenant_id=tenant,
                        business_id=business,
                        name=f"{name} location",
                        address=Address(country_code="ES"),
                        timezone="UTC",
                        operating_hours=OperatingHours(),
                        status=LocationStatus.OPEN,
                    )
                )
                offerings.save(
                    Offering(
                        id=offering,
                        tenant_id=tenant,
                        business_id=business,
                        name=f"{name} offering",
                        description="Synthetic offering",
                        status=CatalogItemStatus.ACTIVE,
                        base_price=Money("12.50", "EUR"),
                        location_ids=frozenset({location}),
                    )
                )
            uow.commit()
    public_orders = SqlitePublicOrders(
        connect=lambda: sqlite3.connect(database_path),
        scopes=scopes,
    )
    first_order = public_orders.create_draft(
        business_slug="first",
        location_slug="main",
        idempotency_key="first-order-0001",
        items=[PublicOrderItem(offering_id=str(first_offering), quantity=Decimal("1"))],
    )
    second_order = public_orders.create_draft(
        business_slug="second",
        location_slug="main",
        idempotency_key="second-order-0001",
        items=[PublicOrderItem(offering_id=str(second_offering), quantity=Decimal("1"))],
    )
    authenticator = StaticBearerAuthenticator(
        {
            "first-staff-token": StaffPrincipal(
                subject="first-user",
                grants=(
                    StaffGrant(
                        business_slug="first",
                        location_slug="main",
                        roles=frozenset({StaffRole.READ_ORDERS}),
                    ),
                ),
            ),
            "second-staff-token": StaffPrincipal(
                subject="second-user",
                grants=(
                    StaffGrant(
                        business_slug="second",
                        location_slug="main",
                        roles=frozenset({StaffRole.READ_ORDERS}),
                    ),
                ),
            ),
        }
    )
    return (
        TestClient(
            create_app(
                staff_authenticator=(
                    auth_wrapper(authenticator) if auth_wrapper else authenticator
                ),
                staff_audit_sink=audit_sink,
                staff_orders=SqliteStaffOrders(
                    connect=lambda: sqlite3.connect(database_path), scopes=scopes
                ),
            )
        ),
        str(first_order["id"]),
        str(second_order["id"]),
    )


def test_staff_order_list_requires_identity_and_enforces_business_isolation(tmp_path) -> None:
    client, _, _ = _staff_client(str(tmp_path / "staff-orders.db"))
    first_route = "/api/v1/staff/businesses/first/locations/main/orders"
    second_route = "/api/v1/staff/businesses/second/locations/main/orders"

    unauthenticated = client.get(first_route)
    allowed = client.get(first_route, headers={"Authorization": "Bearer first-staff-token"})
    forbidden = client.get(second_route, headers={"Authorization": "Bearer first-staff-token"})

    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["www-authenticate"] == "Bearer"
    assert allowed.status_code == 200
    assert [item["status"] for item in allowed.json()["items"]] == ["draft"]
    assert allowed.json()["items"][0]["total"] == {"amount": "12.5000", "currency": "EUR"}
    assert "tenant_id" not in allowed.json()["items"][0]
    assert forbidden.status_code == 403


def test_staff_order_list_rejects_unknown_credentials_and_invalid_limits(tmp_path) -> None:
    client, _, _ = _staff_client(str(tmp_path / "staff-orders.db"))
    route = "/api/v1/staff/businesses/first/locations/main/orders"

    invalid_token = client.get(route, headers={"Authorization": "Bearer unknown-token"})
    invalid_limit = client.get(
        route,
        params={"limit": 101},
        headers={"Authorization": "Bearer first-staff-token"},
    )

    assert invalid_token.status_code == 401
    assert invalid_limit.status_code == 422


def test_static_authenticator_rejects_non_ascii_bearer_tokens() -> None:
    authenticator = StaticBearerAuthenticator(
        {"ascii-token": StaffPrincipal(subject="user", grants=())}
    )

    with pytest.raises(AuthenticationRequired):
        authenticator.authenticate("Bearer café")


def test_staff_order_detail_is_authorized_and_cannot_cross_resource_boundaries(tmp_path) -> None:
    client, first_order_id, second_order_id = _staff_client(str(tmp_path / "staff-orders.db"))
    route = "/api/v1/staff/businesses/first/locations/main/orders"
    headers = {"Authorization": "Bearer first-staff-token"}

    allowed = client.get(f"{route}/{first_order_id}", headers=headers)
    cross_scope = client.get(f"{route}/{second_order_id}", headers=headers)
    malformed = client.get(f"{route}/not-a-uuid", headers=headers)

    assert allowed.status_code == 200
    assert allowed.json()["id"] == first_order_id
    assert cross_scope.status_code == 404
    assert malformed.status_code == 404


def test_staff_authenticator_port_uses_injected_provider_and_server_grants(tmp_path) -> None:
    class DelegatedAuthenticator:
        def __init__(self, delegate: StaticBearerAuthenticator) -> None:
            self._delegate = delegate
            self.calls: list[str | None] = []

        def authenticate(self, authorization: str | None) -> StaffPrincipal:
            self.calls.append(authorization)
            return self._delegate.authenticate(authorization)

    delegates: list[DelegatedAuthenticator] = []

    def wrap(delegate: StaticBearerAuthenticator) -> StaffAuthenticator:
        adapter = DelegatedAuthenticator(delegate)
        delegates.append(adapter)
        return adapter

    client, own_id, foreign_id = _staff_client(
        str(tmp_path / "delegated-staff.db"), auth_wrapper=wrap
    )
    route = "/api/v1/staff/businesses/first/locations/main/orders"
    valid = {"Authorization": "Bearer first-staff-token"}
    assert client.get(route, headers=valid).status_code == 200
    assert client.get(f"{route}/{own_id}", headers=valid).status_code == 200
    assert client.get(f"{route}/{foreign_id}", headers=valid).status_code == 404
    assert (
        client.get(
            "/api/v1/staff/businesses/second/locations/main/orders", headers=valid
        ).status_code
        == 403
    )
    assert client.get(route).status_code == 401
    assert client.get(route, headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert len(delegates) == 1
    assert delegates[0].calls == [
        "Bearer first-staff-token",
        "Bearer first-staff-token",
        "Bearer first-staff-token",
        "Bearer first-staff-token",
        None,
        "Bearer invalid",
    ]


def test_staff_audit_sink_records_minimal_access_outcomes(tmp_path) -> None:
    class CollectingSink:
        def __init__(self) -> None:
            self.events: list[StaffAccessAuditEvent] = []

        def record(self, event: StaffAccessAuditEvent) -> None:
            self.events.append(event)

    sink = CollectingSink()
    client, own_id, foreign_id = _staff_client(str(tmp_path / "audit.db"), audit_sink=sink)
    own_route = "/api/v1/staff/businesses/first/locations/main/orders"
    other_route = "/api/v1/staff/businesses/second/locations/main/orders"
    headers = {"Authorization": "Bearer first-staff-token"}
    responses = [
        client.get(own_route, headers=headers),
        client.get(f"{own_route}/{own_id}", headers=headers),
        client.get(other_route, headers=headers),
        client.get(f"{own_route}/{foreign_id}", headers=headers),
        client.get(own_route),
        client.get(own_route, headers={"Authorization": "Bearer invalid"}),
    ]
    assert [response.status_code for response in responses] == [200, 200, 403, 404, 401, 401]
    assert [event.status_code for event in sink.events] == [200, 200, 403, 404, 401, 401]
    assert [event.action for event in sink.events] == [
        "list_orders",
        "get_order",
        "list_orders",
        "get_order",
        "list_orders",
        "list_orders",
    ]
    assert [event.subject for event in sink.events] == [
        "first-user",
        "first-user",
        "first-user",
        "first-user",
        None,
        None,
    ]
    assert sink.events[2].business_slug == "second"
    assert sink.events[2].location_slug == "main"
    for event, response in zip(sink.events, responses, strict=True):
        assert event.request_id == response.headers["X-Request-ID"]
        assert not hasattr(event, "authorization")
        assert not hasattr(event, "order_id")
        assert "first-staff-token" not in str(event)
        assert own_id not in str(event)
        assert foreign_id not in str(event)


def test_staff_audit_sink_failure_does_not_mask_authorization(tmp_path) -> None:
    class BrokenSink:
        def record(self, event: StaffAccessAuditEvent) -> None:
            raise RuntimeError("Audit storage offline")

    client, _, _ = _staff_client(str(tmp_path / "audit-failure.db"), audit_sink=BrokenSink())
    route = "/api/v1/staff/businesses/first/locations/main/orders"
    assert client.get(route).status_code == 401
    assert (
        client.get(route, headers={"Authorization": "Bearer first-staff-token"}).status_code == 200
    )


def test_staff_audit_is_opt_in_and_absent_when_no_sink_is_composed() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/staff/businesses/first/locations/main/orders")
    assert response.status_code == 503


def test_staff_order_list_is_unavailable_without_explicit_composition() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/staff/businesses/first/locations/main/orders")

    assert response.status_code == 503
