"""Codec JSON v1 explícito para eventos de pedidos."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from universal_business.application.events.reservation_codec import _unique_object, _validate_json
from universal_business.domain.orders.events import (
    OrderCreated,
    OrderLineAdded,
    OrderLineRemoved,
    OrderStatusChanged,
)
from universal_business.domain.orders.value_objects import OrderStatus
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    DomainEventId,
    LocationId,
    OfferingId,
    OrderId,
    TenantId,
)

_TYPES: dict[str, type[DomainEvent]] = {
    "order.created": OrderCreated,
    "order.line_added": OrderLineAdded,
    "order.line_removed": OrderLineRemoved,
    "order.status_changed": OrderStatusChanged,
}


class OrderEventJsonCodec:
    """Codec acotado a eventos de pedidos; conserva instante y offset, no zona IANA."""

    def encode(self, event: DomainEvent, /) -> bytes:
        name = next((name for name, cls in _TYPES.items() if type(event) is cls), None)
        if name is None or event.aggregate_type != "Order":
            raise ValueError("Tipo de evento o agregado de pedido no soportado")
        metadata = dict(event.metadata)
        _validate_json(metadata)
        data: dict[str, Any] = {
            "version": 1,
            "type": name,
            "event_id": str(event.event_id),
            "occurred_at": event.occurred_at.isoformat(),
            "aggregate_id": str(event.aggregate_id),
            "tenant_id": str(event.tenant_id),
            "business_id": str(event.business_id),
            "location_id": str(event.location_id),
            "metadata": metadata,
        }
        if isinstance(event, (OrderLineAdded, OrderLineRemoved)):
            data["offering_id"] = str(event.offering_id)
            data["line_id"] = str(event.line_id)
        if isinstance(event, OrderStatusChanged):
            data["previous_status"] = event.previous_status.value
            data["new_status"] = event.new_status.value
        payload = json.dumps(
            data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        decoded = self.decode(payload)
        if replace(decoded, occurred_at=decoded.occurred_at.astimezone(UTC)) != replace(
            event, occurred_at=event.occurred_at.astimezone(UTC)
        ):
            raise ValueError("El evento no puede reconstruirse sin pérdida")
        return payload

    def decode(self, payload: bytes, /) -> DomainEvent:
        try:
            data = json.loads(payload, object_pairs_hook=_unique_object)
            if not isinstance(data, dict) or type(data.get("version")) is not int:
                raise ValueError("Formato de evento inválido")
            if data["version"] != 1 or data.get("type") not in _TYPES:
                raise ValueError("Versión o tipo de evento no soportado")
            name = data["type"]
            required = {
                "version",
                "type",
                "event_id",
                "occurred_at",
                "aggregate_id",
                "tenant_id",
                "business_id",
                "location_id",
                "metadata",
            }
            if name in ("order.line_added", "order.line_removed"):
                required |= {"offering_id", "line_id"}
            if name == "order.status_changed":
                required |= {"previous_status", "new_status"}
            if set(data) != required or type(data["metadata"]) is not dict:
                raise ValueError("Campos del evento inválidos")
            _validate_json(data["metadata"])
            fields: dict[str, Any] = {
                "event_id": DomainEventId.from_raw(data["event_id"]),
                "occurred_at": datetime.fromisoformat(data["occurred_at"]),
                "aggregate_id": OrderId.from_raw(data["aggregate_id"]),
                "tenant_id": TenantId.from_raw(data["tenant_id"]),
                "business_id": BusinessId.from_raw(data["business_id"]),
                "location_id": LocationId.from_raw(data["location_id"]),
                "metadata": data["metadata"],
            }
            if name in ("order.line_added", "order.line_removed"):
                fields["offering_id"] = OfferingId.from_raw(data["offering_id"])
                fields["line_id"] = UUID(data["line_id"])
            if name == "order.status_changed":
                fields["previous_status"] = OrderStatus(data["previous_status"])
                fields["new_status"] = OrderStatus(data["new_status"])
            return _TYPES[name](**fields)
        except (KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Formato de evento inválido") from exc
