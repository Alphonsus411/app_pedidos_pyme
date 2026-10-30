"""CORS explícito para consumidores web independientes del prototipo."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware


@dataclass(frozen=True)
class ApiCorsSettings:
    """Orígenes permitidos inyectados por entorno, nunca por el navegador."""

    allowed_origins: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.allowed_origins:
            raise ValueError("At least one CORS origin is required")
        if len(set(self.allowed_origins)) != len(self.allowed_origins):
            raise ValueError("CORS origins must not be duplicated")
        for origin in self.allowed_origins:
            parsed = urlparse(origin)
            if (
                not isinstance(origin, str)
                or origin == "*"
                or parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path not in {"", "/"}
                or parsed.params
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.password
            ):
                raise ValueError("CORS origin must be a concrete HTTP(S) origin")


def install_cors(app: FastAPI, settings: ApiCorsSettings | None) -> None:
    """Añade una lista cerrada de orígenes solo cuando el entorno la suministra."""
    if settings is None:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
