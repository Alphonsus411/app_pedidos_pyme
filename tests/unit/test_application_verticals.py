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


class _FailingRegisterExtension:
    """Extension que lanza excepción en su hook register(...)."""

    def __init__(self, name: str, fail_count: int = 1) -> None:
        self._name = name
        self.fail_count = fail_count  # cuántas veces falla antes de OK
        self.attempts = 0
        self.registered: list[VerticalRegistry] = []

    @property
    def name(self) -> str:
        return self._name

    def register(self, context: VerticalRegistry, /) -> None:
        self.attempts += 1
        if self.attempts <= self.fail_count:
            raise RuntimeError(
                f"_FailingRegisterExtension[{self._name}] boom attempt {self.attempts}"
            )
        self.registered.append(context)


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


# ---------- Registry atomicity (hardening 0.2) ----------


def test_register_failure_rolls_back_extensions_list_empty_to_empty() -> None:
    """Registry vacío → extensión falla → sigue vacío (estado previo)."""
    r = VerticalRegistry()
    ext = _FailingRegisterExtension("explosive", fail_count=1)
    snapshot_before = list(r.extensions)
    names_before = r.names()

    with pytest.raises(RuntimeError, match=r"explosive.*boom attempt 1") as excinfo:
        r.register(ext)

    # Error original propagado (no silenciado).
    assert "boom attempt 1" in str(excinfo.value)
    # Estado de la lista idéntico al previo.
    assert r.extensions == snapshot_before == []
    assert r.names() == names_before
    # El hook fue llamado una sola vez.
    assert ext.attempts == 1
    assert ext.registered == []


def test_register_failure_preserves_previously_registered_extensions() -> None:
    """Registry con 2 extensiones OK → 3ª falla → las 2 primeras se conservan intactas."""
    r = VerticalRegistry()
    ext_a = _DummyExtension("alpha")
    ext_b = _DummyExtension("beta")
    r.register(ext_a)
    r.register(ext_b)
    snapshot_before = list(r.extensions)
    names_before = r.names()
    assert names_before == ("alpha", "beta")

    ext_c = _FailingRegisterExtension("gamma-explodes")

    with pytest.raises(RuntimeError, match=r"gamma-explodes"):
        r.register(ext_c)

    # Las extensiones previas se mantienen EXACTAMENTE iguales.
    assert r.names() == names_before
    assert list(r.extensions) == snapshot_before
    assert [e.name for e in r.extensions] == ["alpha", "beta"]
    assert ext_a.registered == [r]
    assert ext_b.registered == [r]
    # ext_c NO quedó registrada parcialmente.
    assert "gamma-explodes" not in r.names()


def test_register_retry_after_failure_eventually_succeeds() -> None:
    """Primer intento falla; segundo intento (hook ahora OK) se registra bien."""
    r = VerticalRegistry()
    # fail_count=1: primer register() lanza, segundo pasa OK.
    ext = _FailingRegisterExtension("will-recover", fail_count=1)

    with pytest.raises(RuntimeError):
        r.register(ext)
    assert ext.attempts == 1
    assert ext.name not in r.names()

    # Retry.
    r.register(ext)
    assert ext.attempts == 2
    assert ext.name in r.names()
    assert ext.registered == [r]


def test_register_double_register_idempotent_survives_prior_failure() -> None:
    """La garantía idempotente de doble registro no se rompe tras fallo previo."""
    r = VerticalRegistry()
    ext = _FailingRegisterExtension("recovered", fail_count=1)

    # 1) falla.
    with pytest.raises(RuntimeError):
        r.register(ext)
    # 2) éxito (segunda llamada del hook pasa).
    r.register(ext)
    assert len(r.extensions) == 1
    assert ext.attempts == 2

    # 3) Tercer intento: mismo nombre distinto objeto → no-op (idempotencia).
    dup = _DummyExtension("recovered")
    r.register(dup)
    assert len(r.extensions) == 1
    assert r.extensions[0] is ext  # el original se mantiene, no dup.
    assert dup.registered == []  # dup nunca llamó a register.
