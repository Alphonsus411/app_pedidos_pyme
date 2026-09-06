"""Tests unitarios — VerticalExtension contract mínimo (ADR-005).

Validamos la puerta sin crear ningún vertical concreto y sin contaminar el
core con nombres sectoriales.
"""

from __future__ import annotations

import pytest

from universal_business.application import VerticalExtension, VerticalRegistry

# ---------- Dummies ----------


class _DummyExtension:
    """Implementa VerticalExtension structuralmente (Protocol @runtime_checkable)."""

    def __init__(self, name: str) -> None:
        self._name = name
        self.registered: list[VerticalRegistry] = []

    @property
    def name(self) -> str:
        return self._name

    def register(self, context: VerticalRegistry, /) -> None:
        self.registered.append(context)


class _BadlyNamedExtension:
    @property
    def name(self) -> str:
        return ""  # ¡nombre inválido!

    def register(self, context: VerticalRegistry, /) -> None:  # pragma: no cover - trivial
        return None


class _NotAnExtension:
    """Falta el hook register, no cumple Protocol structuralmente."""

    @property
    def name(self) -> str:
        return "x"


# ---------- Protocol ----------


def test_protocol_runtime_checkable() -> None:
    assert isinstance(_DummyExtension("alpha"), VerticalExtension)


def test_protocol_rejects_when_missing_register() -> None:
    assert isinstance(_NotAnExtension(), VerticalExtension) is False


# ---------- Registry behavior ----------


def test_registry_registers_extension_and_calls_hook() -> None:
    r = VerticalRegistry()
    ext = _DummyExtension("alpha")
    r.register(ext)
    assert ext.name in r.names()
    assert len(ext.registered) == 1
    assert ext.registered[0] is r


def test_registry_double_register_is_noop_idempotent() -> None:
    r = VerticalRegistry()
    ext1 = _DummyExtension("alpha")
    ext2 = _DummyExtension("alpha")  # mismo name = colisión → no-op segunda vez
    r.register(ext1)
    r.register(ext2)
    # Solo queda el primero (no-op idempotente).
    assert len(r.extensions) == 1
    assert r.extensions[0] is ext1
    # El segundo ext NUNCA recibió register(...)
    assert ext2.registered == []


def test_registry_rejects_empty_name() -> None:
    r = VerticalRegistry()
    with pytest.raises(ValueError, match="extension.name debe ser str no vacío"):
        r.register(_BadlyNamedExtension())


def test_registry_rejects_non_protocol() -> None:
    r = VerticalRegistry()
    with pytest.raises(TypeError, match="expected VerticalExtension Protocol"):
        r.register(_NotAnExtension())  # type: ignore[arg-type]


def test_registry_sorted_is_deterministic() -> None:
    r = VerticalRegistry()
    # Registro en orden aleatorio (z, a, m)
    for name in ["zeta", "alpha", "mu"]:
        r.register(_DummyExtension(name))
    sorted_names = [e.name for e in r.sorted()]
    assert sorted_names == ["alpha", "mu", "zeta"]
