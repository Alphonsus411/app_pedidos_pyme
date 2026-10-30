"""Creación pública de borradores de pedido sobre SQLite."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from apps.api.app.public_catalog import PublicCatalogScope, PublicCatalogUnavailable

from universal_business.application.errors import ApplicationError
from universal_business.application.events.dispatcher import DomainEventDispatcher
from universal_business.application.idempotency import IdempotencyKey
from universal_business.application.orders.commands import AddOrderLine, CreateOrder
from universal_business.domain.catalog.entities import Offering
from universal_business.domain.catalog.value_objects import CatalogItemStatus
from universal_business.domain.orders.entities import Order
from universal_business.domain.orders.line import OrderLine
from universal_business.domain.orders.value_objects import OrderChannel, OrderStatus
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import OfferingId, OrderId
from universal_business.domain.shared.value_objects.money import Money
from universal_business.infrastructure.sqlite_order_execution import SqliteOrderExecution
from universal_business.infrastructure.sqlite_orders import SqliteOrderRepository
from universal_business.infrastructure.sqlite_schema import initialize_sqlite_schema


class PublicOrderRejected(ValueError):
    """La solicitud no puede crear un borrador público seguro."""


class _NoopPublisher:
    def publish(self, event: DomainEvent, /) -> None:
        del event

    def publish_many(self, events: Iterable[DomainEvent], /) -> None:
        del events


class _PublicLinePolicy:
    def approve(self, *, order: Order, offering: Offering, line: OrderLine) -> bool:
        return (
            order.status == OrderStatus.DRAFT
            and offering.status == CatalogItemStatus.ACTIVE
            and line.discount.amount == 0
            and line.tax.amount == 0
        )


class _RejectTransitions:
    def approve(self, *, order: Order, target: OrderStatus) -> bool:
        del order, target
        return False


@dataclass(frozen=True)
class PublicOrderItem:
    offering_id: str
    quantity: Decimal


class SqlitePublicOrders:
    """Compone borradores públicos sin confiar en IDs internos del navegador."""

    def __init__(
        self,
        *,
        connect: Callable[[], sqlite3.Connection],
        scopes: dict[tuple[str, str], PublicCatalogScope],
    ) -> None:
        self._connect = connect
        self._scopes = dict(scopes)

    def create_draft(
        self,
        *,
        business_slug: str,
        location_slug: str,
        idempotency_key: str,
        items: Sequence[PublicOrderItem],
    ) -> dict[str, object]:
        scope = self._scopes.get((business_slug, location_slug))
        if scope is None:
            raise PublicCatalogUnavailable
        if not items:
            raise PublicOrderRejected("At least one item is required")
        request_key = self._request_key(idempotency_key=idempotency_key, items=items)
        order_id = OrderId.from_raw(uuid5(NAMESPACE_URL, f"public-order-v1:{idempotency_key}"))
        try:
            with closing(self._connect()) as connection:
                initialize_sqlite_schema(connection)
                execution = SqliteOrderExecution(
                    connection,
                    dispatcher=DomainEventDispatcher(),
                    publisher=_NoopPublisher(),
                    transition_policy=_RejectTransitions(),
                )
                execution.create(
                    CreateOrder(
                        tenant_id=scope.tenant_id,
                        business_id=scope.business_id,
                        location_id=scope.location_id,
                        order_id=order_id,
                        channel=OrderChannel.WEB,
                        idempotency_key=IdempotencyKey(value=f"create-{request_key}"),
                    )
                )
                for index, item in enumerate(items):
                    execution.add_line(
                        AddOrderLine(
                            tenant_id=scope.tenant_id,
                            business_id=scope.business_id,
                            location_id=scope.location_id,
                            order_id=order_id,
                            offering_id=OfferingId.from_raw(item.offering_id),
                            line_id=uuid5(order_id.raw, f"line:{index}"),
                            quantity=item.quantity,
                            discount=Money("0", "EUR"),
                            tax=Money("0", "EUR"),
                            idempotency_key=IdempotencyKey(value=f"line-{index}-{request_key}"),
                        ),
                        policy=_PublicLinePolicy(),
                    )
                order = SqliteOrderRepository(connection).get(
                    tenant_id=scope.tenant_id,
                    order_id=order_id,
                )
        except (ApplicationError, InvariantViolationError, ValueError) as exc:
            raise PublicOrderRejected("Order request was rejected") from exc
        if order is None or order.total is None:
            raise PublicOrderRejected("Order request was not persisted")
        return {
            "id": str(order.id),
            "status": order.status.value,
            "total": {"amount": str(order.total.amount), "currency": str(order.total.currency)},
        }

    @staticmethod
    def _request_key(*, idempotency_key: str, items: Sequence[PublicOrderItem]) -> str:
        encoded = json.dumps(
            {
                "key": idempotency_key,
                "items": [
                    {"offering_id": item.offering_id, "quantity": str(item.quantity)}
                    for item in items
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
