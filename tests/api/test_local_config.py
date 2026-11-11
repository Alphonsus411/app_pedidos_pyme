"""Composición reproducible de la API local mediante configuración externa."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from apps.api.app.local_config import LocalConfigurationError, create_local_app
from fastapi.testclient import TestClient


def _configuration(database_path: str) -> dict[str, object]:
    return {
        "sqlite_path": database_path,
        "scopes": [
            {
                "business_slug": "demo",
                "location_slug": "main",
                "tenant_id": str(uuid4()),
                "business_id": str(uuid4()),
                "location_id": str(uuid4()),
            }
        ],
        "staff_credentials": [
            {
                "token": "development-staff-token",
                "subject": "development-user",
                "grants": [
                    {
                        "business_slug": "demo",
                        "location_slug": "main",
                        "roles": ["read_orders"],
                    }
                ],
            }
        ],
        "cors_origins": ["https://panel.example.test"],
    }


def test_local_configuration_composes_catalog_orders_staff_and_cors(tmp_path) -> None:
    config_path = tmp_path / "local-api.json"
    config_path.write_text(
        json.dumps(_configuration(str(tmp_path / "prototype.db"))), encoding="utf-8"
    )
    client = TestClient(create_local_app(config_path))

    catalog = client.get("/api/v1/public/businesses/demo/locations/main/catalog")
    staff = client.get(
        "/api/v1/staff/businesses/demo/locations/main/orders",
        headers={"Authorization": "Bearer development-staff-token"},
    )
    cors = client.get("/health", headers={"Origin": "https://panel.example.test"})

    assert catalog.status_code == 200
    assert catalog.json() == {"items": [], "next_cursor": None}
    assert staff.status_code == 200
    assert staff.json() == {"items": []}
    assert cors.headers["access-control-allow-origin"] == "https://panel.example.test"


def test_local_configuration_rejects_unknown_roles_before_serving(tmp_path) -> None:
    config = _configuration(str(tmp_path / "prototype.db"))
    credentials = config["staff_credentials"]
    assert isinstance(credentials, list)
    credentials[0]["grants"][0]["roles"] = ["platform_admin"]
    config_path = tmp_path / "local-api.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(LocalConfigurationError):
        create_local_app(config_path)


@pytest.mark.parametrize(
    ("mutate", "expected_error"),
    [
        (
            lambda config: config["staff_credentials"][0]["grants"][0].update(
                {"business_slug": "unknown"}
            ),
            "Staff grant references an unknown scope",
        ),
        (
            lambda config: config["staff_credentials"][0]["grants"][0].update(
                {"location_slug": "unknown"}
            ),
            "Staff grant references an unknown scope",
        ),
    ],
)
def test_local_configuration_rejects_orphan_staff_grants(tmp_path, mutate, expected_error) -> None:
    config = _configuration(str(tmp_path / "prototype.db"))
    mutate(config)
    config_path = tmp_path / "local-api.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(LocalConfigurationError, match=expected_error):
        create_local_app(config_path)


def test_local_configuration_rejects_conflicting_business_identity(tmp_path) -> None:
    config = _configuration(str(tmp_path / "prototype.db"))
    first_scope = config["scopes"][0]
    config["scopes"].append(
        {
            **first_scope,
            "location_slug": "other",
            "location_id": str(uuid4()),
            "business_id": str(uuid4()),
        }
    )
    config_path = tmp_path / "local-api.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(LocalConfigurationError, match="Business slug has inconsistent identity"):
        create_local_app(config_path)


def test_local_configuration_rejects_republished_location(tmp_path) -> None:
    config = _configuration(str(tmp_path / "prototype.db"))
    config["scopes"].append({**config["scopes"][0], "location_slug": "duplicate"})
    config_path = tmp_path / "local-api.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(LocalConfigurationError, match="Location is published more than once"):
        create_local_app(config_path)


def test_local_configuration_accepts_multiple_locations_of_one_business(tmp_path) -> None:
    config = _configuration(str(tmp_path / "prototype.db"))
    config["scopes"].append(
        {**config["scopes"][0], "location_slug": "other", "location_id": str(uuid4())}
    )
    config_path = tmp_path / "local-api.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    client = TestClient(create_local_app(config_path))
    for location in ("main", "other"):
        result = client.get(f"/api/v1/public/businesses/demo/locations/{location}/catalog")
        assert result.status_code == 200
    staff = client.get(
        "/api/v1/staff/businesses/demo/locations/other/orders",
        headers={"Authorization": "Bearer development-staff-token"},
    )
    assert staff.status_code == 403
