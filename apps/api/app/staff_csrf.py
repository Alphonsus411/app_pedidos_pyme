"""Protección CSRF preparatoria para futuras mutaciones staff por cookie.

Este módulo no publica endpoints, no valida sesiones y no emite cookies.
El futuro controlador DEBE autenticar y autorizar con el lector de sesiones
antes de aceptar la prueba de CSRF y de ejecutar cualquier comando.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Iterable
from urllib.parse import urlsplit


class CsrfRejected(ValueError):
    """El origen o la prueba de sesión no son válidos."""


def _valid_origin(value: str) -> bool:
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError:
        return False
    return (
        url.scheme == "https"
        and bool(url.hostname)
        and url.username is None
        and url.password is None
        and not url.path
        and not url.query
        and not url.fragment
        and port != 0
        and value == f"{url.scheme}://{url.netloc}"
    )


class StaffMutationCsrf:
    """Prueba HMAC ligada a la sesión opaca, al ámbito y al propósito.

    No se aceptan tokens de identidad o grants derivados de cabeceras.
    Es una frontera auxiliar; no reemplaza autorización ni SameSite.
    """

    def __init__(self, *, secret: bytes, allowed_origins: Iterable[str]) -> None:
        origins = tuple(allowed_origins)
        if (
            not isinstance(secret, bytes)
            or len(secret) < 32
            or not origins
            or len(set(origins)) != len(origins)
            or any(not isinstance(origin, str) or not _valid_origin(origin) for origin in origins)
        ):
            raise ValueError("Invalid CSRF configuration")
        self._secret = secret
        self._origins = frozenset(origins)

    def _proof(
        self,
        *,
        session_token: str,
        business_slug: str,
        location_slug: str,
        action: str,
    ) -> str:
        if (
            not isinstance(session_token, str)
            or not 40 <= len(session_token) <= 128
            or not session_token.isascii()
            or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in session_token)
            or any(
                not isinstance(value, str) or not value or len(value) > 128
                for value in (business_slug, location_slug, action)
            )
        ):
            raise CsrfRejected
        # Delimitación no ambigua: longitud de cada campo antes de sus bytes.
        parts = (session_token, business_slug, location_slug, action)
        message = b"staff-csrf-v1\0" + b"".join(
            len(value.encode("utf-8")).to_bytes(4, "big") + value.encode("utf-8")
            for value in parts
        )
        mac = hmac.new(self._secret, message, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")

    def issue_for_trusted_server(
        self,
        *,
        session_token: str,
        business_slug: str,
        location_slug: str,
        action: str,
    ) -> str:
        """Preparar una prueba únicamente después de autenticar la sesión."""
        return self._proof(
            session_token=session_token,
            business_slug=business_slug,
            location_slug=location_slug,
            action=action,
        )

    def verify(
        self,
        *,
        origin: str | None,
        session_token: str,
        csrf_token: str | None,
        business_slug: str,
        location_slug: str,
        action: str,
    ) -> None:
        """Rechazar si falta Origin exacto o la prueba HMAC del ámbito."""
        if origin not in self._origins or not isinstance(csrf_token, str):
            raise CsrfRejected
        if len(csrf_token) != 43 or not csrf_token.isascii():
            raise CsrfRejected
        expected = self._proof(
            session_token=session_token,
            business_slug=business_slug,
            location_slug=location_slug,
            action=action,
        )
        if not hmac.compare_digest(expected, csrf_token):
            raise CsrfRejected
