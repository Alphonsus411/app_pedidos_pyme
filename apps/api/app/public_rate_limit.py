"""Cuota local y opcional de solicitudes POST públicas; no distribuida."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from threading import Lock
from time import monotonic


class LocalPublicOrderRateLimiter:
    """Ventana deslizante por cliente y ruta, con memoria acotada.

    Se requiere un único proceso. No aceptar X-Forwarded-For de clientes;
    el proxy fiable debe resolver la identidad de origen antes de esta capa.
    """

    def __init__(
        self,
        *,
        limit: int = 10,
        window_seconds: float = 60,
        max_clients: int = 2048,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if (
            type(limit) is not int
            or not 1 <= limit <= 10000
            or not math.isfinite(window_seconds)
            or not 0 < window_seconds <= 3600
            or type(max_clients) is not int
            or max_clients < 1
        ):
            raise ValueError("Invalid local rate limit configuration")
        self._limit = limit
        self._window = window_seconds
        self._max_clients = max_clients
        self._clock = clock
        self._lock = Lock()
        self._visits: dict[str, deque[float]] = {}

    def retry_after(self, key: str) -> int | None:
        """None permite la solicitud; un entero positivo indica 429."""
        now = self._clock()
        with self._lock:
            visits = self._visits.get(key)
            if visits is not None:
                while visits and now - visits[0] >= self._window:
                    visits.popleft()
                if not visits:
                    del self._visits[key]
                    visits = None
            if visits is None:
                if len(self._visits) >= self._max_clients:
                    # Fail closed si se agota la capacidad local, sin evicción
                    # arbitraria de clientes activos que permita saltarse límites.
                    return max(1, math.ceil(self._window))
                visits = deque()
                self._visits[key] = visits
            if len(visits) >= self._limit:
                return max(1, math.ceil(self._window - (now - visits[0])))
            visits.append(now)
            return None
