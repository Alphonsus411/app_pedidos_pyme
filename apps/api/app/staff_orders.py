"""Lectura privada de pedidos sobre SQLite con ámbito autorizado en servidor."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import closing

from apps.api.app.public_catalog import PublicCatalogScope
from apps.api.app.staff_auth import StaffPrincipal, StaffRole

from universal_business.application.orders.queries import GetOrder, ListOrdersByLocation
from universal_business.application.orders.query_handlers import (
    GetOrderHandler,
    ListOrdersByLocationHandler,
    OrderView,
)
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import OrderId
from universal_business.infrastructure.sqlite_orders import SqliteOrderRepository
from universal_business.infrastructure.sqlite_schema import initialize_sqlite_schema


class StaffOrdersUnavailable(ValueError):
    """No existe un ámbito de negocio y ubicación publicado para la API."""


class StaffOrdersForbidden(ValueError):
    """El actor autenticado no tiene el permiso requerido en ese ámbito."""


class StaffOrderNotFound(ValueError):
    """El pedido no existe dentro del ámbito autorizado."""


class SqliteStaffOrders:
    """Adaptador de lectura que deriva el ámbito únicamente de la configuración."""

    def __init__(
        self,
        *,
        connect: Callable[[], sqlite3.Connection],
        scopes: dict[tuple[str, str], PublicCatalogScope],
    ) -> None:
        self._connect = connect
        self._scopes = dict(scopes)

    def list_for_location(
        self,
        *,
        principal: StaffPrincipal,
        business_slug: str,
        location_slug: str,
        limit: int,
    ) -> list[dict[str, object]]:
        scope = self._authorized_scope(
            principal=principal,
            business_slug=business_slug,
            location_slug=location_slug,
        )
        with closing(self._connect()) as connection:
            initialize_sqlite_schema(connection)
            views = ListOrdersByLocationHandler(orders=SqliteOrderRepository(connection)).handle(
                ListOrdersByLocation(
                    tenant_id=scope.tenant_id,
                    business_id=scope.business_id,
                    location_id=scope.location_id,
                    limit=limit,
                )
            )
        return [_serialize(view) for view in views]

    def get_for_location(
        self,
        *,
        principal: StaffPrincipal,
        business_slug: str,
        location_slug: str,
        order_id: str,
    ) -> dict[str, object]:
        scope = self._authorized_scope(
            principal=principal,
            business_slug=business_slug,
            location_slug=location_slug,
        )
        try:
            parsed_order_id = OrderId.from_raw(order_id)
        except InvariantViolationError as exc:
            raise StaffOrderNotFound from exc
        with closing(self._connect()) as connection:
            initialize_sqlite_schema(connection)
            view = GetOrderHandler(orders=SqliteOrderRepository(connection)).handle(
                GetOrder(
                    tenant_id=scope.tenant_id,
                    business_id=scope.business_id,
                    location_id=scope.location_id,
                    order_id=parsed_order_id,
                )
            )
        if view is None:
            raise StaffOrderNotFound
        return _serialize(view)

    def _authorized_scope(
        self,
        *,
        principal: StaffPrincipal,
        business_slug: str,
        location_slug: str,
    ) -> PublicCatalogScope:
        scope = self._scopes.get((business_slug, location_slug))
        if scope is None:
            raise StaffOrdersUnavailable
        if not principal.allows(
            business_slug=business_slug,
            location_slug=location_slug,
            role=StaffRole.READ_ORDERS,
        ):
            raise StaffOrdersForbidden
        return scope


def _serialize(view: OrderView) -> dict[str, object]:
    return {
        "id": str(view.order_id),
        "status": view.status.value,
        "total": (
            {"amount": str(view.total.amount), "currency": str(view.total.currency)}
            if view.total is not None
            else None
        ),
        "created_at": view.created_at.isoformat(),
    }
