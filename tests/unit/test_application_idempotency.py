"""Tests unitarios — Idempotency (IdempotencyKey + IdempotencyStore Protocol)."""

from __future__ import annotations

import inspect

import pytest

from universal_business.application.idempotency import (
    IdempotencyKey,
    IdempotencyStore,
    InvalidIdempotencyKeyError,
)
from universal_business.domain.shared.value_objects.ids import TenantId

# ---------- Fake IdempotencyStore (solo tests) ----------


class FakeIdempotencyStore:
    """Implementación doble en memoria del IdempotencyStore Protocol.

    Estado interno por ``(tenant_id, key)``: ``FREE`` / ``RESERVED`` / ``DONE``.
    """

    FREE = "FREE"
    RESERVED = "RESERVED"
    DONE = "DONE"

    def __init__(self) -> None:
        # clave: tuple[TenantId, IdempotencyKey] → tupla[estado_str, request_digest, obj]
        self._data: dict[tuple[TenantId, IdempotencyKey], tuple[str, str, object]] = {}

    def _k(self, tenant_id: TenantId, key: IdempotencyKey) -> tuple[TenantId, IdempotencyKey]:
        return (tenant_id, key)

    def get(self, tenant_id: TenantId, key: IdempotencyKey, /) -> tuple[str, object] | None:
        entry = self._data.get(self._k(tenant_id, key))
        if entry is None:
            return None
        state, req_digest, obj = entry
        if state != self.DONE:
            return None
        return (req_digest, obj)

    def reserve(self, tenant_id: TenantId, key: IdempotencyKey, request_digest: str, /) -> bool:
        k = self._k(tenant_id, key)
        if k not in self._data:
            self._data[k] = (self.RESERVED, request_digest, None)
            return True
        state, _req, _obj = self._data[k]
        if state == self.FREE:  # pragma: no cover - estado no alcanzable en este fake simple
            self._data[k] = (self.RESERVED, request_digest, None)
            return True
        return False

    def complete(
        self,
        tenant_id: TenantId,
        key: IdempotencyKey,
        result_digest: str,
        result_object: object = None,
        /,
    ) -> None:
        k = self._k(tenant_id, key)
        # Permitimos complete(...) incluso si no hubo reserve explícito (simplifica tests).
        self._data[k] = (self.DONE, result_digest, result_object)


# ---------- Protocol ----------


def test_store_protocol_members_require_tenant_id_in_signature() -> None:
    members = ["get", "reserve", "complete"]
    for m in members:
        assert hasattr(IdempotencyStore, m)
        sig = inspect.signature(getattr(IdempotencyStore, m))
        assert "tenant_id" in sig.parameters, (
            f"IdempotencyStore.{m} debe llevar tenant_id explícito"
        )


def test_fake_store_implements_protocol_at_runtime() -> None:
    assert isinstance(FakeIdempotencyStore(), IdempotencyStore) is True


# ---------- IdempotencyKey validación ----------


def test_key_valid_ok() -> None:
    k = IdempotencyKey(value="abc123-XY_zz")
    assert str(k) == "abc123-XY_zz"


def test_key_too_short_error() -> None:
    with pytest.raises(InvalidIdempotencyKeyError):
        IdempotencyKey(value="short")


def test_key_invalid_chars_error() -> None:
    with pytest.raises(InvalidIdempotencyKeyError):
        IdempotencyKey(value="bad key with spaces!!!!!!!!!!!!!!!")  # len >8 pero space


def test_key_non_str_error() -> None:
    with pytest.raises(InvalidIdempotencyKeyError):
        IdempotencyKey(value=123456789)  # type: ignore[arg-type]


# ---------- Flujo completo ----------


def test_first_operation_succeeds() -> None:
    store = FakeIdempotencyStore()
    tid = TenantId.generate()
    key = IdempotencyKey(value="idemp-00001-first")
    assert store.reserve(tid, key, "req-abc") is True
    # Después de reserve, get() devuelve None (aún no terminado).
    assert store.get(tid, key) is None
    store.complete(tid, key, "res-xyz", 42)
    entry = store.get(tid, key)
    assert entry is not None
    assert entry[0] == "res-xyz"
    assert entry[1] == 42


def test_duplicate_operation_is_conflict() -> None:
    store = FakeIdempotencyStore()
    tid = TenantId.generate()
    key = IdempotencyKey(value="idemp-00002-dupe")
    assert store.reserve(tid, key, "req-abc") is True
    store.complete(tid, key, "res-xyz")
    # Segundo intento → reserve devuelve False (conflicto).
    assert store.reserve(tid, key, "req-abc") is False


def test_tenant_isolation_same_key_different_tenants() -> None:
    store = FakeIdempotencyStore()
    tid_a = TenantId.generate()
    tid_b = TenantId.generate()
    assert tid_a != tid_b
    key = IdempotencyKey(value="shared-key-1111")
    assert store.reserve(tid_a, key, "req1") is True
    assert store.reserve(tid_b, key, "req1") is True  # Distinto tenant = ok
    store.complete(tid_a, key, "res-a", {"a": 1})
    store.complete(tid_b, key, "res-b", {"b": 9})
    assert store.get(tid_a, key)[1] == {"a": 1}
    assert store.get(tid_b, key)[1] == {"b": 9}
