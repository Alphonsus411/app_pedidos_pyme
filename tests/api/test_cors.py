"""CORS explícito y restringido para aplicaciones web independientes."""

from __future__ import annotations

import pytest
from apps.api.app.cors import ApiCorsSettings
from apps.api.app.main import create_app
from fastapi.testclient import TestClient


def test_cors_only_allows_explicitly_configured_origin() -> None:
    client = TestClient(create_app(cors_settings=ApiCorsSettings(("https://site.example.test",))))

    allowed = client.options(
        "/api/v1/public/businesses/demo/locations/main/catalog",
        headers={
            "Origin": "https://site.example.test",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization, X-Request-ID",
        },
    )
    rejected = client.options(
        "/api/v1/public/businesses/demo/locations/main/catalog",
        headers={
            "Origin": "https://other.example.test",
            "Access-Control-Request-Method": "GET",
        },
    )
    actual = client.get("/health", headers={"Origin": "https://site.example.test"})

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://site.example.test"
    assert "authorization" in allowed.headers["access-control-allow-headers"].lower()
    assert actual.headers["access-control-allow-origin"] == "https://site.example.test"
    assert actual.headers["access-control-expose-headers"] == "X-Request-ID"
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers


def test_cors_is_not_enabled_without_explicit_environment_configuration() -> None:
    response = TestClient(create_app()).get(
        "/health", headers={"Origin": "https://site.example.test"}
    )

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize(
    "origin",
    (
        "*",
        "https://site.example.test/path",
        "ftp://site.example.test",
        "https://user@site.example.test",
    ),
)
def test_cors_rejects_wildcards_and_non_origin_values(origin: str) -> None:
    with pytest.raises(ValueError):
        ApiCorsSettings((origin,))
