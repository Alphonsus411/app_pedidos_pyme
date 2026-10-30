"""Identidad técnica mínima para rutas privadas del prototipo local.

Este adaptador no emite tokens ni sustituye un proveedor de identidad. Recibe
credenciales estáticas inyectadas por el entorno para poder probar la frontera
de autorización y el aislamiento entre negocios sin introducir secretos en el
núcleo ni en clientes web.
"""

from __future__ import annotations

import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class AuthenticationRequired(ValueError):
    """No se presentó una credencial Bearer válida."""


class StaffRole(StrEnum):
    """Permisos mínimos publicados para el primer endpoint privado."""

    READ_ORDERS = "read_orders"


@dataclass(frozen=True)
class StaffGrant:
    """Un permiso limitado a un negocio y ubicación configurados por servidor."""

    business_slug: str
    location_slug: str
    roles: frozenset[StaffRole]

    def allows(self, *, business_slug: str, location_slug: str, role: StaffRole) -> bool:
        return (
            self.business_slug == business_slug
            and self.location_slug == location_slug
            and role in self.roles
        )


@dataclass(frozen=True)
class StaffPrincipal:
    """Actor autenticado y sus permisos de ámbito, sin datos de negocio."""

    subject: str
    grants: tuple[StaffGrant, ...]

    def allows(self, *, business_slug: str, location_slug: str, role: StaffRole) -> bool:
        return any(
            grant.allows(
                business_slug=business_slug,
                location_slug=location_slug,
                role=role,
            )
            for grant in self.grants
        )


class StaticBearerAuthenticator:
    """Valida Bearer tokens inyectados, exclusivamente para desarrollo y pruebas."""

    def __init__(self, credentials: Mapping[str, StaffPrincipal]) -> None:
        self._credentials = dict(credentials)

    def authenticate(self, authorization: str | None) -> StaffPrincipal:
        if authorization is None:
            raise AuthenticationRequired
        scheme, separator, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not separator or not token or token.strip() != token:
            raise AuthenticationRequired
        for configured_token, principal in self._credentials.items():
            if hmac.compare_digest(configured_token, token):
                return principal
        raise AuthenticationRequired
