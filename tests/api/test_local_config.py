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
