"""Contratos para la creación pública y aislada de borradores de pedido."""

from __future__ import annotations

import sqlite3

from apps.api.app.main import create_app
from apps.api.app.public_catalog import PublicCatalogScope
from apps.api.app.public_orders import SqlitePublicOrders
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


def _orders_client(database_path: str) -> tuple[TestClient, str]:
    tenant, business, location = TenantId.generate(), BusinessId.generate(), LocationId.generate()
    offering_id = OfferingId.generate()
    with sqlite3.connect(database_path) as connection:
        initialize_sqlite_schema(connection)
        with SqliteUnitOfWork(connection) as uow:
            SqliteLocationRepository(connection).save(
                Location(
                    id=location,
                    tenant_id=tenant,
                    business_id=business,
                    name="Public location",
                    address=Address(country_code="ES"),
                    timezone="UTC",
                    operating_hours=OperatingHours(),
                    status=LocationStatus.OPEN,
                )
            )
            SqliteOfferingRepository(connection).save(
                Offering(
                    id=offering_id,
                    tenant_id=tenant,
                    business_id=business,
                    name="Public offering",
                    description="Available through the public API",
                    status=CatalogItemStatus.ACTIVE,
                    base_price=Money("12.50", "EUR"),
                    location_ids=frozenset({location}),
                )
            )
            uow.commit()
    orders = SqlitePublicOrders(
        connect=lambda: sqlite3.connect(database_path),
        scopes={
            ("first", "main"): PublicCatalogScope(
                tenant_id=tenant,
                business_id=business,
                location_id=location,
            )
        },
    )
    return TestClient(create_app(public_orders=orders)), str(offering_id)


def test_public_order_creates_a_draft_and_replays_the_same_request(tmp_path) -> None:
    client, offering_id = _orders_client(str(tmp_path / "orders.db"))
    route = "/api/v1/public/businesses/first/locations/main/orders"
    request = {"items": [{"offering_id": offering_id, "quantity": "2"}]}
    headers = {"Idempotency-Key": "public-order-0001"}

    created = client.post(route, json=request, headers=headers)
    replay = client.post(route, json=request, headers=headers)

    assert created.status_code == 201
    assert replay.status_code == 201
    assert created.json() == replay.json()
    assert created.json()["status"] == "draft"
    assert created.json()["total"] == {"amount": "25.0000", "currency": "EUR"}


def test_public_order_rejects_a_changed_request_with_the_same_idempotency_key(tmp_path) -> None:
    client, offering_id = _orders_client(str(tmp_path / "orders.db"))
    route = "/api/v1/public/businesses/first/locations/main/orders"
    headers = {"Idempotency-Key": "public-order-0001"}

    assert (
        client.post(
            route,
            json={"items": [{"offering_id": offering_id, "quantity": "2"}]},
            headers=headers,
        ).status_code
        == 201
    )
    changed = client.post(
        route,
        json={"items": [{"offering_id": offering_id, "quantity": "3"}]},
        headers=headers,
    )

    assert changed.status_code == 409


def test_public_order_does_not_start_when_service_is_not_composed() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/public/businesses/first/locations/main/orders",
        json={"items": [{"offering_id": "missing", "quantity": "1"}]},
        headers={"Idempotency-Key": "public-order-0001"},
    )

    assert response.status_code == 503
