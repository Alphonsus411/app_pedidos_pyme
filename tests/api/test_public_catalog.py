"""Contratos del catálogo público sobre SQLite real y dos ámbitos aislados."""

from __future__ import annotations

import sqlite3

from apps.api.app.main import create_app
from apps.api.app.public_catalog import PublicCatalogScope, SqlitePublicCatalog
from fastapi.testclient import TestClient

from universal_business.domain.catalog.entities import Offering
from universal_business.domain.catalog.value_objects import CatalogItemStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    OfferingId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money
from universal_business.infrastructure.sqlite_offerings import SqliteOfferingRepository
from universal_business.infrastructure.sqlite_schema import initialize_sqlite_schema
from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork


def _catalog_client(database_path: str) -> TestClient:
    first_tenant, second_tenant = TenantId.generate(), TenantId.generate()
    first_business, second_business = BusinessId.generate(), BusinessId.generate()
    first_location, second_location = LocationId.generate(), LocationId.generate()
    with sqlite3.connect(database_path) as connection:
        initialize_sqlite_schema(connection)
        with SqliteUnitOfWork(connection) as uow:
            repository = SqliteOfferingRepository(connection)
            repository.save(
                Offering(
                    id=OfferingId.generate(),
                    tenant_id=first_tenant,
                    business_id=first_business,
                    name="Visible first",
                    description="Only for the first business",
                    status=CatalogItemStatus.ACTIVE,
                    base_price=Money("12.50", "EUR"),
                    location_ids=frozenset({first_location}),
                )
            )
            repository.save(
                Offering(
                    id=OfferingId.generate(),
                    tenant_id=first_tenant,
                    business_id=first_business,
                    name="Alpha first",
                    description="First page item",
                    status=CatalogItemStatus.ACTIVE,
                    base_price=Money("4.00", "EUR"),
                    location_ids=frozenset({first_location}),
                )
            )
            repository.save(
                Offering(
                    id=OfferingId.generate(),
                    tenant_id=first_tenant,
                    business_id=first_business,
                    name="Bravo first",
                    description="Second page item",
                    status=CatalogItemStatus.ACTIVE,
                    base_price=Money("6.00", "EUR"),
                    location_ids=frozenset({first_location}),
                )
            )
            repository.save(
                Offering(
                    id=OfferingId.generate(),
                    tenant_id=first_tenant,
                    business_id=first_business,
                    name="Hidden inactive",
                    status=CatalogItemStatus.INACTIVE,
                    base_price=Money("9.00", "EUR"),
                )
            )
            repository.save(
                Offering(
                    id=OfferingId.generate(),
                    tenant_id=second_tenant,
                    business_id=second_business,
                    name="Visible second",
                    status=CatalogItemStatus.ACTIVE,
                    base_price=Money("8.00", "EUR"),
                    location_ids=frozenset({second_location}),
                )
            )
            uow.commit()
    catalog = SqlitePublicCatalog(
        connect=lambda: sqlite3.connect(database_path),
        scopes={
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
        },
    )
    return TestClient(create_app(public_catalog=catalog))


def test_public_catalog_only_returns_active_items_from_server_resolved_scope(tmp_path) -> None:
    client = _catalog_client(str(tmp_path / "catalog.db"))

    response = client.get("/api/v1/public/businesses/first/locations/main/catalog")

    assert response.status_code == 200
    item = response.json()["items"]
    assert [entry["name"] for entry in item] == ["Alpha first", "Bravo first", "Visible first"]
    assert item[2]["description"] == "Only for the first business"
    assert item[2]["price"] == {"amount": "12.5000", "currency": "EUR"}
    assert response.json()["next_cursor"] is None


def test_public_catalog_does_not_cross_business_boundaries_or_accept_unknown_scope(
    tmp_path,
) -> None:
    client = _catalog_client(str(tmp_path / "catalog.db"))

    second = client.get("/api/v1/public/businesses/second/locations/main/catalog")
    unknown = client.get("/api/v1/public/businesses/first/locations/other/catalog")

    assert [item["name"] for item in second.json()["items"]] == ["Visible second"]
    assert "tenant_id" not in second.json()["items"][0]
    assert "business_id" not in second.json()["items"][0]
    assert unknown.status_code == 404


def test_public_catalog_uses_an_opaque_cursor_without_crossing_scope(tmp_path) -> None:
    client = _catalog_client(str(tmp_path / "catalog.db"))
    route = "/api/v1/public/businesses/first/locations/main/catalog"

    first = client.get(route, params={"limit": 1})
    second = client.get(route, params={"limit": 1, "cursor": first.json()["next_cursor"]})
    last = client.get(route, params={"limit": 1, "cursor": second.json()["next_cursor"]})

    assert first.status_code == second.status_code == last.status_code == 200
    assert first.json()["items"][0]["name"] == "Alpha first"
    assert second.json()["items"][0]["name"] == "Bravo first"
    assert last.json()["items"][0]["name"] == "Visible first"
    assert last.json()["next_cursor"] is None


def test_public_catalog_rejects_invalid_cursor_with_the_api_error_contract(tmp_path) -> None:
    client = _catalog_client(str(tmp_path / "catalog.db"))

    response = client.get(
        "/api/v1/public/businesses/first/locations/main/catalog",
        params={"cursor": "not-a-cursor"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
