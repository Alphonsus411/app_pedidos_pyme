"""Selección explícita de codec para una cola mixta de pedidos y reservas."""

import json

from universal_business.application.events.order_codec import OrderEventJsonCodec
from universal_business.application.events.reservation_codec import (
    ReservationEventJsonCodec,
    _unique_object,
)
from universal_business.domain.orders.events import (
    OrderCreated,
    OrderLineAdded,
    OrderLineRemoved,
    OrderStatusChanged,
)
from universal_business.domain.reservations.events import (
    ReservationCancelled,
    ReservationConfirmed,
    ReservationCreated,
    ReservationStatusChanged,
)
from universal_business.domain.shared.events import DomainEvent


class BusinessEventJsonCodec:
    """Codec de la cola común; delega únicamente en los tipos conocidos."""

    def __init__(self) -> None:
        self._orders = OrderEventJsonCodec()
        self._reservations = ReservationEventJsonCodec()

    def encode(self, event: DomainEvent, /) -> bytes:
        if type(event) in (OrderCreated, OrderLineAdded, OrderLineRemoved, OrderStatusChanged):
            return self._orders.encode(event)
        if type(event) in (
            ReservationCreated,
            ReservationConfirmed,
            ReservationCancelled,
            ReservationStatusChanged,
        ):
            return self._reservations.encode(event)
        raise ValueError("Tipo de evento no soportado")

    def decode(self, payload: bytes, /) -> DomainEvent:
        try:
            data = json.loads(payload, object_pairs_hook=_unique_object)
            event_type = data.get("type") if isinstance(data, dict) else None
            if isinstance(event_type, str) and event_type.startswith("order."):
                return self._orders.decode(payload)
            if isinstance(event_type, str) and event_type.startswith("reservation."):
                return self._reservations.decode(payload)
            raise ValueError("Tipo de evento no soportado")
        except (TypeError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Formato de evento inválido") from exc
