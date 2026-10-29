"""Idempotencia SQLite para los resultados explícitos del ciclo de pedidos."""

import json
from decimal import Context, Decimal, localcontext
from typing import Any
from uuid import UUID

from universal_business.application.orders.add_line import OrderLineResult
from universal_business.application.orders.creation import OrderDraftCreated
from universal_business.application.orders.remove_line import OrderLineRemoval
from universal_business.application.orders.status_change import OrderStatusResult
from universal_business.domain.orders.value_objects import OrderStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    OfferingId,
    OrderId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money
from universal_business.infrastructure.sqlite_idempotency import SqliteReservationIdempotencyStore


class SqliteOrderIdempotencyStore(SqliteReservationIdempotencyStore):
    """Almacén por ejecución. Complete puede ser postcommit o dentro de la UoW.

    Para atomicidad usar complete_in_uow junto con pedido y outbox en la misma
    conexión; el ejecutor genérico usa complete postcommit y puede dejar RESERVED.
    """

    def _encode_result(self, value: object) -> str:
        types = (OrderDraftCreated, OrderLineResult, OrderLineRemoval, OrderStatusResult)
        if type(value) not in types:
            raise ValueError("Resultado de pedido no soportado")
        assert isinstance(value, types)
        kind = {
            OrderDraftCreated: "draft",
            OrderLineResult: "line_added",
            OrderLineRemoval: "line_removed",
            OrderStatusResult: "status",
        }[type(value)]
        data = dict(
            version=1,
            kind=kind,
            tenant=str(value.tenant_id),
            business=str(value.business_id),
            location=str(value.location_id),
            order=str(value.order_id),
        )
        if isinstance(value, (OrderLineResult, OrderLineRemoval)):
            data["line"] = str(value.line_id)
        if isinstance(value, OrderLineResult):
            data["offering"] = str(value.offering_id)
        if isinstance(value, OrderStatusResult):
            if not isinstance(value.status, OrderStatus):
                raise ValueError("Estado inválido")
            data["status"] = value.status.value
        if isinstance(value, (OrderLineResult, OrderLineRemoval, OrderStatusResult)):
            total = value.total
            if total is not None and (type(total) is not Money or not total.amount.is_finite()):
                raise ValueError("Total inválido")
            if isinstance(value, OrderLineResult) and total is None:
                raise ValueError("Total inválido")
            data["total"] = (
                None
                if total is None
                else {"amount": str(total.amount), "currency": str(total.currency)}
            )
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def _decode_result(self, payload: str) -> object:
        data = json.loads(payload)
        if type(data) is not dict or type(data.get("version")) is not int or data["version"] != 1:
            raise ValueError("Resultado de pedido inválido")
        kind = data.get("kind")
        fields = {"version", "kind", "tenant", "business", "location", "order"}
        extras = {
            "draft": set(),
            "line_added": {"line", "offering", "total"},
            "line_removed": {"line", "total"},
            "status": {"status", "total"},
        }
        if type(kind) is not str or kind not in extras or set(data) != fields | extras[kind]:
            raise ValueError("Resultado de pedido inválido")
        args: dict[str, Any] = dict(
            tenant_id=TenantId.from_raw(data["tenant"]),
            business_id=BusinessId.from_raw(data["business"]),
            location_id=LocationId.from_raw(data["location"]),
            order_id=OrderId.from_raw(data["order"]),
        )
        if kind == "draft":
            return OrderDraftCreated(**args)
        raw = data["total"]
        total = None
        if raw is not None:
            if (
                type(raw) is not dict
                or set(raw) != {"amount", "currency"}
                or type(raw["amount"]) is not str
                or type(raw["currency"]) is not str
            ):
                raise ValueError("Total inválido")
            amount = Decimal(raw["amount"])
            with localcontext(Context(prec=50)):
                total = Money(amount, raw["currency"])
            if not total.amount.is_finite() or total.amount != amount:
                raise ValueError("Total inválido")
        if kind == "status":
            return OrderStatusResult(**args, status=OrderStatus(data["status"]), total=total)
        line = UUID(data["line"])
        if kind == "line_removed":
            return OrderLineRemoval(**args, line_id=line, total=total)
        if total is None:
            raise ValueError("Total inválido")
        return OrderLineResult(
            **args, line_id=line, offering_id=OfferingId.from_raw(data["offering"]), total=total
        )
