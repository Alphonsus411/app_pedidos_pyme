"""Tests unitarios para IDs fuertes."""

from __future__ import annotations

import uuid

import pytest

from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import (
    BaseStrongId,
    BusinessId,
    CatalogItemId,
    CustomerId,
    DomainEventId,
    FulfillmentId,
    LocationId,
    OrderId,
    ReservationId,
    ResourceId,
    TenantId,
)

ALL_ID_TYPES = [
    TenantId,
    BusinessId,
    LocationId,
    CustomerId,
    CatalogItemId,
    ResourceId,
    ReservationId,
    OrderId,
    FulfillmentId,
    DomainEventId,
]


@pytest.mark.parametrize("cls", ALL_ID_TYPES)
def test_id_generate_returns_same_type(cls: type[BaseStrongId]) -> None:
    i = cls.generate()
    assert isinstance(i, cls)
    assert isinstance(i.raw, uuid.UUID)


@pytest.mark.parametrize("cls", ALL_ID_TYPES)
def test_id_is_hashable_and_eq_by_value(cls: type[BaseStrongId]) -> None:
    u = uuid.uuid4()
    a = cls(raw=u)
    b = cls(raw=u)
    assert a == b
    assert hash(a) == hash(b)
    assert {a: "ok"}[b] == "ok"


def test_ids_are_distinct_types() -> None:
    u = uuid.uuid4()
    t = TenantId(raw=u)
    b = BusinessId(raw=u)
    assert t != b  # igual UUID pero distinto tipo
    assert hash(t) != hash(b) or type(t) is not type(b)
    # Específicamente: la igualdad debe fallar entre tipos distintos
    assert not (t == b)


@pytest.mark.parametrize("cls", ALL_ID_TYPES)
def test_id_from_raw_uuid_str(cls: type[BaseStrongId]) -> None:
    u = uuid.uuid4()
    a = cls.from_raw(str(u))
    assert a.raw == u
    b = cls.from_raw(u)
    assert b.raw == u
    c = cls.from_raw(u.int)
    assert c.raw == u
    d = cls.from_raw(u.bytes)
    assert d.raw == u


@pytest.mark.parametrize("cls", ALL_ID_TYPES)
def test_id_from_raw_invalid_raises(cls: type[BaseStrongId]) -> None:
    with pytest.raises(InvariantViolationError):
        cls.from_raw("not-a-uuid")
    with pytest.raises(InvariantViolationError):
        cls.from_raw(3.14)  # type: ignore[arg-type]


def test_id_str_representation_is_readable() -> None:
    u = uuid.UUID("11111111-2222-3333-4444-555555555555")
    t = TenantId(raw=u)
    assert str(t) == str(u)
    assert repr(t) == f"TenantId({str(u)})"
