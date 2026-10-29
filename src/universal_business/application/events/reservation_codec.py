"""Codec JSON v1 para eventos de reserva, con tipos explícitos permitidos."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from universal_business.domain.reservations.events import (
    ReservationCancelled,
    ReservationConfirmed,
    ReservationCreated,
    ReservationStatusChanged,
)
from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    DomainEventId,
    LocationId,
    ReservationId,
    ResourceId,
    TenantId,
)

_TYPES: dict[str, type[DomainEvent]] = {
    "reservation.created": ReservationCreated,
    "reservation.confirmed": ReservationConfirmed,
    "reservation.cancelled": ReservationCancelled,
    "reservation.status_changed": ReservationStatusChanged,
}


def _validate_json(value: Any) -> None:
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is list:
        for item in value:
            _validate_json(item)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _validate_json(item)
        return
    raise ValueError("metadata solo admite JSON sin números flotantes")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Campo JSON duplicado")
        result[key] = value
    return result


class ReservationEventJsonCodec:
    """Serialización v1 limitada a los cuatro tipos de eventos de reserva.

    Rechaza campos desconocidos y tipos no admitidos para evitar pérdida
    silenciosa de datos. La fecha conserva instante y offset, pero ISO 8601
    no conserva el nombre de zona IANA. No importa clases del documento.
    """

    def encode(self, event: DomainEvent, /) -> bytes:
        name = next((name for name, cls in _TYPES.items() if type(event) is cls), None)
        if name is None:
            raise ValueError("Tipo de evento de reserva no soportado")
        if not isinstance(
            event,
            (
                ReservationCreated,
                ReservationConfirmed,
                ReservationCancelled,
                ReservationStatusChanged,
            ),
        ):
            raise ValueError("Tipo de evento de reserva no soportado")
        if event.aggregate_type != "Reservation":
            raise ValueError("Tipo de agregado inválido")
        metadata = dict(event.metadata)
        _validate_json(metadata)
        # Los cuatro tipos del registro declaran los campos de ámbito.
        data: dict[str, Any] = {
            "version": 1,
            "type": name,
            "event_id": str(event.event_id),
            "occurred_at": event.occurred_at.isoformat(),
            "aggregate_id": str(event.aggregate_id),
            "tenant_id": str(event.tenant_id),
            "business_id": str(event.business_id),
            "location_id": str(event.location_id),
            "resource_id": str(event.resource_id),
            "metadata": metadata,
        }
        if isinstance(event, ReservationStatusChanged):
            data["previous_status"] = event.previous_status.value
            data["new_status"] = event.new_status.value
        payload = json.dumps(
            data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        decoded = self.decode(payload)
        # ISO 8601 preserves the instant and offset, not the ZoneInfo key.
        # Python equality for ambiguous local times differs between ZoneInfo
        # and fixed offsets, so compare both event instants in UTC.
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
                "resource_id",
                "metadata",
            }
            if name == "reservation.status_changed":
                required |= {"previous_status", "new_status"}
            if set(data) != required or type(data["metadata"]) is not dict:
                raise ValueError("Campos del evento inválidos")
            _validate_json(data["metadata"])
            fields: dict[str, Any] = {
                "event_id": DomainEventId.from_raw(data["event_id"]),
                "occurred_at": datetime.fromisoformat(data["occurred_at"]),
                "aggregate_id": ReservationId.from_raw(data["aggregate_id"]),
                "tenant_id": TenantId.from_raw(data["tenant_id"]),
                "business_id": BusinessId.from_raw(data["business_id"]),
                "location_id": LocationId.from_raw(data["location_id"]),
                "resource_id": ResourceId.from_raw(data["resource_id"]),
                "metadata": data["metadata"],
            }
            if name == "reservation.status_changed":
                fields["previous_status"] = ReservationStatus(data["previous_status"])
                fields["new_status"] = ReservationStatus(data["new_status"])
            return _TYPES[name](**fields)
        except (KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Formato de evento inválido") from exc
