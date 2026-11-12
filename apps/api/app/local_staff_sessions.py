"""Sesiones opacas de laboratorio: almacenamiento en memoria del servidor.

No incluye login, endpoint de emisión ni proveedor de identidad. El servicio de
confianza que emita una sesión deberá validar previamente al usuario.
"""

from __future__ import annotations

import hashlib
import math
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from time import monotonic

from apps.api.app.staff_auth import AuthenticationRequired, StaffPrincipal
from starlette.requests import Request

COOKIE_NAME = "__Host-ub_session"


@dataclass(frozen=True, slots=True)
class _Session:
    principal: StaffPrincipal
    expires_at: float


class LocalOpaqueStaffSessions:
    """Puerto StaffSessionReader con expiración absoluta y revocación explícita.

    Almacena solo el SHA-256 del token; no comparte estado entre procesos.
    Se usa únicamente por composición explícita en pruebas y laboratorio.
    """

    def __init__(
        self,
        *,
        lifetime_seconds: float = 900,
        max_sessions: int = 1024,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if (
            not math.isfinite(lifetime_seconds)
            or not 0 < lifetime_seconds <= 86400
            or type(max_sessions) is not int
            or not 1 <= max_sessions <= 100000
        ):
            raise ValueError("Invalid laboratory session configuration")
        self._lifetime = lifetime_seconds
        self._max_sessions = max_sessions
        self._clock = clock
        self._lock = Lock()
        self._sessions: dict[str, _Session] = {}

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def _prune(self, now: float) -> None:
        for digest, session in list(self._sessions.items()):
            if now >= session.expires_at:
                del self._sessions[digest]

    def issue_for_trusted_server(self, principal: StaffPrincipal) -> str:
        """Emitir solo desde código servidor tras verificar la identidad.

        No llamar desde endpoints públicos ni desde un navegador.
        """
        if not principal.subject or not principal.subject.strip():
            raise ValueError("Invalid principal")
        now = self._clock()
        with self._lock:
            self._prune(now)
            if len(self._sessions) >= self._max_sessions:
                raise RuntimeError("Laboratory session capacity exceeded")
            token = secrets.token_urlsafe(32)
            self._sessions[self._digest(token)] = _Session(principal, now + self._lifetime)
            return token

    def revoke(self, token: str) -> None:
        if not token or not token.isascii():
            return
        with self._lock:
            self._sessions.pop(self._digest(token), None)

    def current_principal(self, request: Request) -> StaffPrincipal:
        token = request.cookies.get(COOKIE_NAME)
        if (
            token is None
            or not token.isascii()
            or not 40 <= len(token) <= 128
            or any(
                c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
                for c in token
            )
        ):
            raise AuthenticationRequired
        now = self._clock()
        with self._lock:
            session = self._sessions.get(self._digest(token))
            if session is None:
                raise AuthenticationRequired
            if now >= session.expires_at:
                del self._sessions[self._digest(token)]
                raise AuthenticationRequired
            return session.principal


def session_cookie_header(token: str, *, max_age: int = 900) -> str:
    """Cabecera de transporte HTTPS para una futura ruta de login confiable.

    El helper NO emite sesiones ni instala una cookie desde un endpoint.
    """
    if (
        not token.isascii()
        or len(token) != 43
        or any(
            c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
            for c in token
        )
        or type(max_age) is not int
        or not 1 <= max_age <= 86400
    ):
        raise ValueError("Invalid cookie parameters")
    return f"{COOKIE_NAME}={token}; Path=/; Max-Age={max_age}; Secure; HttpOnly; SameSite=Strict"
