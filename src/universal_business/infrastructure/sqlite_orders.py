"""Repositorio SQLite de pedidos; el esquema se instala explícitamente."""

import json
import sqlite3
from datetime import datetime
from decimal import Context, Decimal, localcontext
from typing import Any
from uuid import UUID

from universal_business.application.errors import ApplicationError
from universal_business.domain.orders.entities import Order
from universal_business.domain.orders.line import OrderLine
from universal_business.domain.orders.value_objects import OrderChannel, OrderStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CustomerId,
    LocationId,
    OfferingId,
    OrderId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money
from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork


def create_sqlite_orders_schema(connection: sqlite3.Connection) -> None:
    """Crear tabla de pedidos; no modifica esquemas ni versiones existentes."""
    connection.execute("""CREATE TABLE IF NOT EXISTS orders (
        tenant_id TEXT NOT NULL, id TEXT NOT NULL, business_id TEXT NOT NULL,
        location_id TEXT NOT NULL, customer_id TEXT, status TEXT NOT NULL,
        channel TEXT NOT NULL, external_ref TEXT, notes TEXT, payload TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        PRIMARY KEY (tenant_id, id)
    )""")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS orders_location ON orders (tenant_id, location_id, status)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS orders_customer ON orders (tenant_id, customer_id, status)"
    )


def _money(value: Money | None) -> dict[str, str] | None:
    if value is None:
        return None
    if type(value) is not Money or not value.amount.is_finite():
        raise ValueError("Importe inválido")
    return {"amount": str(value.amount), "currency": str(value.currency)}


def _read_money(value: Any) -> Money | None:
    if value is None:
        return None
    if (
        type(value) is not dict
        or set(value) != {"amount", "currency"}
        or any(type(value[k]) is not str for k in value)
    ):
        raise ValueError("Importe inválido")
    amount = Decimal(value["amount"])
    with localcontext(Context(prec=50)):
        money = Money(amount, value["currency"])
    if not money.amount.is_finite() or money.amount != amount:
        raise ValueError("Importe inválido")
    return money


def _payload(order: Order) -> str:
    if type(order) is not Order or any(type(line) is not OrderLine for line in order.lines):
        raise ValueError("Tipo de pedido o línea no soportado")
    lines = [
        dict(
            id=str(line.line_id),
            offering=str(line.offering_id),
            name=line.name,
            quantity=str(line.quantity),
            unit_price=_money(line.unit_price),
            discount=_money(line.discount),
            tax=_money(line.tax),
        )
        for line in order.lines
    ]
    return json.dumps(
        {"version": 1, "total": _money(order.total), "lines": lines},
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _read(row: tuple[Any, ...]) -> Order:
    data = json.loads(row[9])
    if (
        type(data) is not dict
        or set(data) != {"version", "total", "lines"}
        or type(data["version"]) is not int
        or data["version"] != 1
        or type(data["lines"]) is not list
    ):
        raise ValueError("Pedido SQLite inválido")
    lines = []
    for line in data["lines"]:
        if type(line) is not dict or set(line) != {
            "id",
            "offering",
            "name",
            "quantity",
            "unit_price",
            "discount",
            "tax",
        }:
            raise ValueError("Línea SQLite inválida")
        price, discount, tax = (
            _read_money(line["unit_price"]),
            _read_money(line["discount"]),
            _read_money(line["tax"]),
        )
        if price is None or discount is None or tax is None or type(line["quantity"]) is not str:
            raise ValueError("Importes de línea inválidos")
        lines.append(
            OrderLine(
                line_id=UUID(line["id"]),
                offering_id=OfferingId.from_raw(line["offering"]),
                name=line["name"],
                quantity=Decimal(line["quantity"]),
                unit_price=price,
                discount=discount,
                tax=tax,
            )
        )
    total = _read_money(data["total"])
    if lines and total is None:
        raise ValueError("Total de pedido con líneas ausente")
    order = Order(
        tenant_id=TenantId.from_raw(row[0]),
        id=OrderId.from_raw(row[1]),
        business_id=BusinessId.from_raw(row[2]),
        location_id=LocationId.from_raw(row[3]),
        customer_id=CustomerId.from_raw(row[4]) if row[4] else None,
        status=OrderStatus(row[5]),
        channel=OrderChannel(row[6]),
        external_ref=row[7],
        notes=row[8],
        total=total,
        lines=tuple(lines),
        created_at=datetime.fromisoformat(row[10]),
        updated_at=datetime.fromisoformat(row[11]),
    )
    order.clear_domain_events()
    return order


class SqliteOrderRepository:
    """Aislamiento por tenant y transacción activa, sin autorización ni migración."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, *, tenant_id: TenantId, order_id: OrderId) -> Order | None:
        row = self._connection.execute(
            "SELECT * FROM orders WHERE tenant_id=? AND id=?", (str(tenant_id), str(order_id))
        ).fetchone()
        return _read(row) if row else None

    def save(self, order: Order) -> None:
        if not self._connection.in_transaction:
            raise RuntimeError("La escritura requiere una transacción activa")
        result = self._connection.execute(
            """INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id,id) DO UPDATE SET customer_id=excluded.customer_id, status=excluded.status,
            channel=excluded.channel, external_ref=excluded.external_ref, notes=excluded.notes,
            payload=excluded.payload, updated_at=excluded.updated_at
            WHERE orders.business_id=excluded.business_id AND orders.location_id=excluded.location_id
            AND orders.created_at=excluded.created_at""",
            (
                str(order.tenant_id),
                str(order.id),
                str(order.business_id),
                str(order.location_id),
                str(order.customer_id) if order.customer_id else None,
                order.status.value,
                order.channel.value,
                order.external_ref,
                order.notes,
                _payload(order),
                order.created_at.isoformat(),
                order.updated_at.isoformat(),
            ),
        )
        if result.rowcount != 1:
            raise ValueError("No se puede cambiar ámbito o fecha de creación")

    def list_by_location(
        self,
        *,
        tenant_id: TenantId,
        location_id: LocationId,
        status: OrderStatus | None = None,
        limit: int = 50,
    ) -> list[Order]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Límite inválido")
        if status is not None and not isinstance(status, OrderStatus):
            raise ValueError("Estado inválido")
        sql = "SELECT * FROM orders WHERE tenant_id=? AND location_id=?"
        params: list[object] = [str(tenant_id), str(location_id)]
        if status is not None:
            sql += " AND status=?"
            params.append(status.value)
        params.append(limit)
        return [
            _read(row)
            for row in self._connection.execute(sql + " ORDER BY id LIMIT ?", params).fetchall()
        ]

    def list_by_customer(
        self, *, tenant_id: TenantId, customer_id: CustomerId, status: OrderStatus | None = None
    ) -> list[Order]:
        if status is not None and not isinstance(status, OrderStatus):
            raise ValueError("Estado inválido")
        sql = "SELECT * FROM orders WHERE tenant_id=? AND customer_id=?"
        params: list[object] = [str(tenant_id), str(customer_id)]
        if status is not None:
            sql += " AND status=?"
            params.append(status.value)
        return [_read(row) for row in self._connection.execute(sql, params).fetchall()]


class SqliteOrderMutationGuard:
    """Protección asociada a una UoW SQLite con BEGIN IMMEDIATE.

    Todas las mutaciones deben usar protección compatible y compartir la misma
    conexión hasta commit o rollback. No protege el catálogo ni autoriza al actor.
    """

    def __init__(self, uow: SqliteUnitOfWork) -> None:
        self._uow = uow

    def protect(
        self,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId,
        order_id: OrderId,
    ) -> None:
        self._uow.require_active()
        if not (
            isinstance(tenant_id, TenantId)
            and isinstance(business_id, BusinessId)
            and isinstance(location_id, LocationId)
            and isinstance(order_id, OrderId)
        ):
            raise ApplicationError("Order no encontrado o fuera del ámbito")
        order = SqliteOrderRepository(self._uow.connection).get(
            tenant_id=tenant_id, order_id=order_id
        )
        if order is None or (order.tenant_id, order.business_id, order.location_id, order.id) != (
            tenant_id,
            business_id,
            location_id,
            order_id,
        ):
            raise ApplicationError("Order no encontrado o fuera del ámbito")
