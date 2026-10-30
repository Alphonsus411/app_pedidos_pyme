"""Contrato HTTP de identidad técnica y aislamiento para pedidos de personal."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from apps.api.app.main import create_app
from apps.api.app.public_catalog import PublicCatalogScope
from apps.api.app.public_orders import PublicOrderItem, SqlitePublicOrders
from apps.api.app.staff_auth import StaffGrant, StaffPrincipal, StaffRole, StaticBearerAuthenticator
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


def _staff_client(database_path: str) -> TestClient:
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
    public_orders.create_draft(
        business_slug="first",
        location_slug="main",
        idempotency_key="first-order-0001",
        items=[PublicOrderItem(offering_id=str(first_offering), quantity=Decimal("1"))],
    )
    public_orders.create_draft(
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
    return TestClient(
        create_app(
            staff_authenticator=authenticator,
            staff_orders=SqliteStaffOrders(
                connect=lambda: sqlite3.connect(database_path), scopes=scopes
            ),
        )
    )


def test_staff_order_list_requires_identity_and_enforces_business_isolation(tmp_path) -> None:
    client = _staff_client(str(tmp_path / "staff-orders.db"))
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
    client = _staff_client(str(tmp_path / "staff-orders.db"))
    route = "/api/v1/staff/businesses/first/locations/main/orders"

    invalid_token = client.get(route, headers={"Authorization": "Bearer unknown-token"})
    invalid_limit = client.get(
        route,
        params={"limit": 101},
        headers={"Authorization": "Bearer first-staff-token"},
    )

    assert invalid_token.status_code == 401
    assert invalid_limit.status_code == 422


def test_staff_order_list_is_unavailable_without_explicit_composition() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/staff/businesses/first/locations/main/orders")

    assert response.status_code == 503
