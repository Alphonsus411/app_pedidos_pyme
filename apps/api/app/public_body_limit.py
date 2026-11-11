"""Límite de bytes reales del cuerpo para POST público de pedidos.

Adaptador ASGI, sin dependencia de dominio o persistencia. Acota el buffer
antes de entregar el cuerpo a FastAPI/Pydantic, también para streaming.
"""

from __future__ import annotations

import re

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_PUBLIC_ORDER_PATH = re.compile(r"/api/v1/public/businesses/[^/]+/locations/[^/]+/orders")


class PublicOrderBodySizeMiddleware:
    """Límite local del cuerpo HTTP; no sustituye controles del proxy."""

    def __init__(self, app: ASGIApp, *, max_bytes: int = 32 * 1024) -> None:
        if type(max_bytes) is not int or not 1 <= max_bytes <= 1024 * 1024:
            raise ValueError("Invalid public order body size limit")
        self._app = app
        self._limit = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or _PUBLIC_ORDER_PATH.fullmatch(scope.get("path", "")) is None
        ):
            await self._app(scope, receive, send)
            return

        # La cabecera permite abortar sin leer; no se confía en ella para el
        # tamaño real y se vuelve a contar cada byte recibido.
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0
                if declared > self._limit:
                    await self._reject(scope, receive, send)
                    return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            chunk = message.get("body", b"")
            if len(chunk) > self._limit - len(body):
                await self._reject(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        delivered = False

        async def replay_receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self._app(scope, replay_receive, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        request_id = scope.get("state", {}).get("request_id")
        if not isinstance(request_id, str):
            # Compatibilidad si se compone el ASGI middleware aisladamente.
            from uuid import uuid4

            request_id = str(uuid4())
        response = JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "payload_too_large",
                    "message": "Public order body exceeds the configured limit",
                    "request_id": request_id,
                }
            },
        )
        await response(scope, receive, send)
