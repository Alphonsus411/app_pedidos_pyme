"""Contrato común de errores y correlación del adaptador HTTP."""

from __future__ import annotations

from uuid import UUID

from apps.api.app.main import create_app
from fastapi.testclient import TestClient


def test_error_response_is_safe_and_has_generated_request_correlation() -> None:
    response = TestClient(create_app()).get("/api/v1/public/businesses/demo/locations/main/catalog")

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "service_unavailable",
        "message": "Public catalog is not configured",
        "request_id": response.headers["x-request-id"],
    }
    UUID(response.headers["x-request-id"])


def test_validation_error_uses_contract_and_preserves_valid_request_id() -> None:
    request_id = "123e4567-e89b-12d3-a456-426614174000"
    response = TestClient(create_app()).get(
        "/api/v1/staff/businesses/demo/locations/main/orders",
        params={"limit": 101},
        headers={"X-Request-ID": request_id},
    )

    assert response.status_code == 422
    assert response.headers["x-request-id"] == request_id
    assert response.json()["error"] == {
        "code": "validation_error",
        "message": "Request validation failed",
        "request_id": request_id,
    }


def test_malformed_request_id_is_replaced_and_missing_route_is_not_found() -> None:
    response = TestClient(create_app()).get("/api/v1/missing", headers={"X-Request-ID": "bad"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    UUID(response.headers["x-request-id"])
