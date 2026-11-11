"""Contratos para la creación pública y aislada de borradores de pedido."""

from __future__ import annotations

import sqlite3
from uuid import NAMESPACE_URL, uuid5

from apps.api.app import public_orders
from apps.api.app.main import create_app
from apps.api.app.public_catalog import PublicCatalogScope
from apps.api.app.public_orders import PublicOrderItem, SqlitePublicOrders
from fastapi.testclient import TestClient

from universal_business.application.events.dispatcher import DomainEventDispatcher
from universal_business.application.idempotency import IdempotencyKey
from universal_business.application.orders.commands import AddOrderLine, CreateOrder
from universal_business.domain.business.entities import Location
from universal_business.domain.business.value_objects import Address, LocationStatus, OperatingHours
from universal_business.domain.catalog.entities import Offering
from universal_business.domain.catalog.value_objects import CatalogItemStatus
from universal_business.domain.orders.value_objects import OrderChannel
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    OfferingId,
    OrderId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money
from universal_business.infrastructure.sqlite_locations import SqliteLocationRepository
from universal_business.infrastructure.sqlite_offerings import SqliteOfferingRepository
from universal_business.infrastructure.sqlite_order_execution import SqliteOrderExecution
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


def test_public_order_rolls_back_all_lines_on_second_line_failure(tmp_path) -> None:
    path = str(tmp_path / "rollback.db")
    client, offering_id = _orders_client(path)
    route = "/api/v1/public/businesses/first/locations/main/orders"
    headers = {"Idempotency-Key": "public-order-multiline-1"}
    bad = "00000000-0000-4000-8000-000000000099"
    response = client.post(
        route,
        json={
            "items": [
                {"offering_id": offering_id, "quantity": "2"},
                {"offering_id": bad, "quantity": "1"},
            ]
        },
        headers=headers,
    )
    assert response.status_code == 409
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM idempotency").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM transactional_outbox").fetchone()[0] == 0

    valid = {
        "items": [
            {"offering_id": offering_id, "quantity": "2"},
            {"offering_id": offering_id, "quantity": "1"},
        ]
    }
    success = client.post(route, json=valid, headers=headers)
    assert success.status_code == 201
    assert success.json()["total"] == {"amount": "37.5000", "currency": "EUR"}
    replay = client.post(route, json=valid, headers=headers)
    assert replay.status_code == 201
    assert replay.json() == success.json()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM idempotency").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM transactional_outbox").fetchone()[0] == 3


def test_public_order_multiline_rejects_changed_payload(tmp_path) -> None:
    client, offering_id = _orders_client(str(tmp_path / "conflict.db"))
    route = "/api/v1/public/businesses/first/locations/main/orders"
    headers = {"Idempotency-Key": "public-order-multiline-2"}
    first = {
        "items": [
            {"offering_id": offering_id, "quantity": "2"},
            {"offering_id": offering_id, "quantity": "1"},
        ]
    }
    altered = {
        "items": [
            {"offering_id": offering_id, "quantity": "2"},
            {"offering_id": offering_id, "quantity": "3"},
        ]
    }
    assert client.post(route, json=first, headers=headers).status_code == 201
    assert client.post(route, json=altered, headers=headers).status_code == 409


def test_public_order_same_key_is_isolated_across_businesses_and_locations(tmp_path) -> None:
    path = str(tmp_path / "scopes.db")
    tenant = TenantId.generate()
    scopes = {}
    offerings = {}
    with sqlite3.connect(path) as connection:
        initialize_sqlite_schema(connection)
        with SqliteUnitOfWork(connection) as uow:
            for slug in ("first", "second"):
                business = BusinessId.generate()
                location = LocationId.generate()
                offering_id = OfferingId.generate()
                SqliteLocationRepository(connection).save(
                    Location(
                        id=location,
                        tenant_id=tenant,
                        business_id=business,
                        name=f"{slug} location",
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
                        name=f"{slug} offering",
                        description="Synthetic example",
                        status=CatalogItemStatus.ACTIVE,
                        base_price=Money("12.50", "EUR"),
                        location_ids=frozenset({location}),
                    )
                )
                scopes[(slug, "main")] = PublicCatalogScope(
                    tenant_id=tenant, business_id=business, location_id=location
                )
                offerings[slug] = str(offering_id)
            uow.commit()
    client = TestClient(
        create_app(
            public_orders=SqlitePublicOrders(connect=lambda: sqlite3.connect(path), scopes=scopes)
        )
    )
    headers = {"Idempotency-Key": "shared-client-key"}
    identifiers = []
    for slug in ("first", "second"):
        url = f"/api/v1/public/businesses/{slug}/locations/main/orders"
        body = {"items": [{"offering_id": offerings[slug], "quantity": "1"}]}
        created = client.post(url, json=body, headers=headers)
        replay = client.post(url, json=body, headers=headers)
        assert created.status_code == replay.status_code == 201
        assert created.json() == replay.json()
        identifiers.append(created.json()["id"])
    assert identifiers[0] != identifiers[1]
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 2


def test_public_order_replays_legacy_identifier_in_original_scope(tmp_path) -> None:
    path = str(tmp_path / "legacy.db")
    client, offering_id = _orders_client(path)
    url = "/api/v1/public/businesses/first/locations/main/orders"
    key = "legacy-id-replay"
    body = {"items": [{"offering_id": offering_id, "quantity": "1"}]}
    # This is the ID that a previous version would have generated.
    legacy_id = OrderId.from_raw(uuid5(NAMESPACE_URL, f"public-order-v1:{key}"))
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT tenant_id, business_id, id FROM locations"
        ).fetchone()
        assert row is not None
        tenant_id, business_id, location_id = row
    # Recreate that historical state through the old deterministic-ID code path.
    scope = PublicCatalogScope(
        tenant_id=TenantId.from_raw(tenant_id),
        business_id=BusinessId.from_raw(business_id),
        location_id=LocationId.from_raw(location_id),
    )
    item = PublicOrderItem(offering_id=offering_id, quantity=Money("1", "EUR").amount)
    request_key = SqlitePublicOrders._request_key(idempotency_key=key, items=[item])
    with sqlite3.connect(path) as connection:
        execution = SqliteOrderExecution(
            connection,
            dispatcher=DomainEventDispatcher(),
            publisher=public_orders._NoopPublisher(),
            transition_policy=public_orders._RejectTransitions(),
        )
        execution.create_with_lines(
            CreateOrder(
                tenant_id=scope.tenant_id,
                business_id=scope.business_id,
                location_id=scope.location_id,
                order_id=legacy_id,
                channel=OrderChannel.WEB,
                idempotency_key=IdempotencyKey(value=f"create-{request_key}"),
            ),
            [
                AddOrderLine(
                    tenant_id=scope.tenant_id,
                    business_id=scope.business_id,
                    location_id=scope.location_id,
                    order_id=legacy_id,
                    offering_id=OfferingId.from_raw(offering_id),
                    line_id=uuid5(legacy_id.raw, "line:0"),
                    quantity=item.quantity,
                    discount=Money("0", "EUR"),
                    tax=Money("0", "EUR"),
                    idempotency_key=IdempotencyKey(value=f"line-0-{request_key}"),
                )
            ],
            policy=public_orders._PublicLinePolicy(),
        )
    replay = client.post(url, json=body, headers={"Idempotency-Key": key})
    assert replay.status_code == 201
    assert replay.json()["id"] == str(legacy_id)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1


def test_public_order_does_not_start_when_service_is_not_composed() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/public/businesses/first/locations/main/orders",
        json={"items": [{"offering_id": "missing", "quantity": "1"}]},
        headers={"Idempotency-Key": "public-order-0001"},
    )

    assert response.status_code == 503
