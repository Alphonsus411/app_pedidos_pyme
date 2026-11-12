"""Contrato de lectura de sesión staff; sin implementación de login ni tokens.

La identidad y sus grants proceden exclusivamente de un proveedor confiable
inyectado en el servidor. Esta capa no crea, firma ni guarda sesiones.
"""

from __future__ import annotations

from typing import Protocol

from apps.api.app.staff_auth import StaffPrincipal
from starlette.requests import Request


class StaffSessionReader(Protocol):
    def current_principal(self, request: Request) -> StaffPrincipal:
        """Validar sesión de servidor o lanzar AuthenticationRequired."""
        ...


def authorized_staff_scopes(
    principal: StaffPrincipal,
    *,
    published_scopes: frozenset[tuple[str, str]],
) -> list[dict[str, object]]:
    """Intersección de permisos del actor y ámbitos publicados por servidor.

    La autorización de cada recurso se sigue verificando en su endpoint.
    El descubrimiento no concede permisos ni permite crear ámbitos.
    """
    valid: dict[tuple[str, str], set[str]] = {}
    for grant in principal.grants:
        scope = (grant.business_slug, grant.location_slug)
        if scope in published_scopes:
            valid.setdefault(scope, set()).update(role.value for role in grant.roles)
    return [
        {"business_slug": business, "location_slug": location, "roles": sorted(roles)}
        for (business, location), roles in sorted(valid.items())
        if roles
    ]
