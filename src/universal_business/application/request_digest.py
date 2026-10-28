"""Versioned, deterministic fingerprints for supported idempotent commands.

The format deliberately rejects unsupported values instead of falling back to repr.
Changing the format requires a new version and an explicit migration policy.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, cast
from uuid import UUID


def _encode(value: object) -> object:
    if value is None or type(value) in (bool, int, str):
        return value
    if isinstance(value, Enum):
        return [
            "enum",
            f"{type(value).__module__}.{type(value).__qualname__}",
            _encode(value.value),
        ]
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Naive datetime is not supported in idempotency requests")
        return ["datetime-utc", value.astimezone(UTC).isoformat(timespec="microseconds")]
    if isinstance(value, UUID):
        return ["uuid", str(value)]
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite Decimal is not supported in idempotency requests")
        return ["decimal", str(value)]
    if is_dataclass(value) and not isinstance(value, type):
        data = cast(Any, value)
        return [
            "dataclass",
            f"{type(value).__module__}.{type(value).__qualname__}",
            [[field.name, _encode(getattr(data, field.name))] for field in fields(data)],
        ]
    if isinstance(value, (set, frozenset)):
        encoded = [_encode(item) for item in value]
        encoded.sort(key=lambda item: json.dumps(item, ensure_ascii=False, separators=(",", ":")))
        return ["set", encoded]
    if isinstance(value, (list, tuple)):
        return ["sequence", [_encode(item) for item in value]]
    raise TypeError(f"Unsupported idempotency request value: {type(value).__name__}")


def request_digest(command: object) -> str:
    """Hash a command without its transport key; include command type and all other fields."""
    if not is_dataclass(command) or isinstance(command, type):
        raise TypeError("Idempotency request must be a dataclass instance")
    data = cast(Any, command)
    payload = [
        "idempotency-request-v1",
        f"{type(command).__module__}.{type(command).__qualname__}",
        [
            [field.name, _encode(getattr(data, field.name))]
            for field in fields(data)
            if field.name != "idempotency_key"
        ],
    ]
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "v1:" + hashlib.sha256(raw).hexdigest()
