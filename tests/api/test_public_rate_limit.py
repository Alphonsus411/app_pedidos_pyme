"""Pruebas deterministas del limitador opcional del adaptador HTTP."""

from __future__ import annotations

from apps.api.app.main import create_app
from apps.api.app.public_rate_limit import LocalPublicOrderRateLimiter
from fastapi.testclient import TestClient


def _order_payload() -> dict[str, object]:
    return {"items": [{"offering_id": "00000000-0000-4000-8000-000000000099", "quantity": "1"}]}


def test_public_order_limiter_rejects_with_429_and_correlation_id() -> None:
    current = [100.0]
    limiter = LocalPublicOrderRateLimiter(limit=2, window_seconds=60, clock=lambda: current[0])
    client = TestClient(create_app(public_order_limiter=limiter))
    url = "/api/v1/public/businesses/first/locations/main/orders"
    headers = {"Idempotency-Key": "sample-request"}
    assert client.post(url, json=_order_payload(), headers=headers).status_code == 503
    assert client.post(url, json=_order_payload(), headers=headers).status_code == 503
    blocked = client.post(url, json=_order_payload(), headers=headers)
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "60"
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert blocked.json()["error"]["request_id"] == blocked.headers["X-Request-ID"]
    assert client.get("/health").status_code == 200

    current[0] += 60
    assert client.post(url, json=_order_payload(), headers=headers).status_code == 503


def test_public_order_limiter_isolates_public_paths() -> None:
    limiter = LocalPublicOrderRateLimiter(limit=1, window_seconds=60, clock=lambda: 5.0)
    client = TestClient(create_app(public_order_limiter=limiter))
    headers = {"Idempotency-Key": "sample-request"}
    first = "/api/v1/public/businesses/first/locations/main/orders"
    second = "/api/v1/public/businesses/second/locations/main/orders"
    assert client.post(first, json=_order_payload(), headers=headers).status_code == 503
    assert client.post(first, json=_order_payload(), headers=headers).status_code == 429
    assert client.post(second, json=_order_payload(), headers=headers).status_code == 503


def test_local_limiter_fails_closed_at_capacity_and_recovers_after_expiry() -> None:
    current = [1.0]
    limiter = LocalPublicOrderRateLimiter(
        limit=1, window_seconds=10, max_clients=1, clock=lambda: current[0]
    )
    assert limiter.retry_after("first") is None
    assert limiter.retry_after("first") == 10
    assert limiter.retry_after("second") == 10
    current[0] += 10
    assert limiter.retry_after("second") is None


def test_local_limiter_rejects_invalid_configuration() -> None:
    from pytest import raises

    with raises(ValueError):
        LocalPublicOrderRateLimiter(limit=0)
    with raises(ValueError):
        LocalPublicOrderRateLimiter(max_clients=0)
    with raises(ValueError):
        LocalPublicOrderRateLimiter(window_seconds=float("nan"))


def test_default_app_has_no_public_order_rate_limit() -> None:
    client = TestClient(create_app())
    url = "/api/v1/public/businesses/first/locations/main/orders"
    for _ in range(3):
        assert (
            client.post(url, json=_order_payload(), headers={"Idempotency-Key": "test"}).status_code
            == 503
        )
