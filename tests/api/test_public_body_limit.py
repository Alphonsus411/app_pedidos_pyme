"""Regresiones de tamaño bruto de POST públicos, incluso por fragmentos."""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from apps.api.app.main import create_app
from apps.api.app.public_body_limit import PublicOrderBodySizeMiddleware
from fastapi.testclient import TestClient

PUBLIC_ORDER_URL = "/api/v1/public/businesses/demo/locations/main/orders"
VALID_BODY = b'{"items":[{"offering_id":"00000000-0000-4000-8000-000000000099","quantity":"1"}]}'


def test_oversized_public_order_is_413_before_validation() -> None:
    client = TestClient(create_app(public_order_max_body_bytes=64))
    result = client.post(
        PUBLIC_ORDER_URL,
        content=VALID_BODY,
        headers={"Content-Type": "application/json", "Idempotency-Key": "test"},
    )
    assert result.status_code == 413
    assert result.json()["error"]["code"] == "payload_too_large"
    assert result.headers["X-Request-ID"] == result.json()["error"]["request_id"]
    UUID(result.headers["X-Request-ID"])


def test_bounded_public_order_preserves_previous_contract() -> None:
    client = TestClient(create_app(public_order_max_body_bytes=len(VALID_BODY)))
    result = client.post(
        PUBLIC_ORDER_URL,
        content=VALID_BODY,
        headers={"Content-Type": "application/json", "Idempotency-Key": "test"},
    )
    assert result.status_code == 503
    assert client.get("/health").status_code == 200
    assert (
        client.post(
            "/api/v1/public/businesses/demo/locations/main/other",
            content=b"x" * 512,
        ).status_code
        == 404
    )


def test_rejects_real_chunked_bytes_without_content_length() -> None:
    calls = []

    async def inner(scope, receive, send) -> None:
        calls.append("entered")
        message = await receive()
        assert message["body"] == VALID_BODY
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def invoke(chunks: list[bytes], *, max_bytes: int) -> tuple[list[dict], list[str]]:
        request_messages = iter(
            [
                {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
                for index, chunk in enumerate(chunks)
            ]
        )
        responses = []

        async def receive() -> dict:
            return next(request_messages)

        async def send(message: dict) -> None:
            responses.append(message)

        app = PublicOrderBodySizeMiddleware(inner, max_bytes=max_bytes)
        scope = {
            "type": "http",
            "method": "POST",
            "path": PUBLIC_ORDER_URL,
            "headers": [],
            "state": {"request_id": "fixed-id"},
        }
        await app(scope, receive, send)
        return responses, calls

    rejected, entered = asyncio.run(
        invoke([VALID_BODY[:30], VALID_BODY[30:]], max_bytes=len(VALID_BODY) - 1)
    )
    assert rejected[0]["status"] == 413
    assert entered == []

    valid, entered = asyncio.run(
        invoke([VALID_BODY[:30], VALID_BODY[30:]], max_bytes=len(VALID_BODY))
    )
    assert valid[0]["status"] == 204
    assert entered == ["entered"]


def test_declared_content_length_rejection_does_not_read_body() -> None:
    async def inner(scope, receive, send) -> None:
        raise AssertionError("Should not enter application")

    async def receive() -> dict:
        raise AssertionError("Should not read oversized body")

    responses = []

    async def send(message: dict) -> None:
        responses.append(message)

    app = PublicOrderBodySizeMiddleware(inner, max_bytes=64)
    scope = {
        "type": "http",
        "method": "POST",
        "path": PUBLIC_ORDER_URL,
        "headers": [(b"content-length", b"1000")],
        "state": {"request_id": "fixed-id"},
    }
    asyncio.run(app(scope, receive, send))
    assert responses[0]["status"] == 413


@pytest.mark.parametrize("value", [0, -1, 1024 * 1024 + 1, True])
def test_invalid_body_size_configuration(value) -> None:
    with pytest.raises(ValueError):
        PublicOrderBodySizeMiddleware(create_app(), max_bytes=value)


def test_body_limit_opt_in_keeps_default_app_behavior() -> None:
    client = TestClient(create_app())
    result = client.post(
        PUBLIC_ORDER_URL,
        content=VALID_BODY,
        headers={"Content-Type": "application/json", "Idempotency-Key": "test"},
    )
    assert result.status_code == 503
