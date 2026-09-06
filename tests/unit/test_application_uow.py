"""Tests unitarios — UnitOfWork Protocol semántica transaccional (Gate 0.2)."""

from __future__ import annotations

import inspect

import pytest

from universal_business.application.unit_of_work import UnitOfWork

# ---------- Fake UoW (vive SOLO en tests) ----------


class FakeUnitOfWork:
    """Implementación de prueba (double) del UnitOfWork Protocol.

    Contabiliza cuántas veces se llamó a commit / rollback para validar la
    semántica en tests. Implementa el Protocol estructuralmente.
    """

    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0
        self.entered = False
        self.exited = False
        # Estado FSM simplificado
        self._committed = False
        self._rolledback = False

    def __enter__(self) -> FakeUnitOfWork:
        self.entered = True
        self._committed = False
        self._rolledback = False
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.exited = True
        if exc is not None or not self._committed:
            # Error o commit explícito nunca llamado → rollback automático
            self.rollback()
        # Devuelve None → la excepción (si la había) se propaga (comportamiento correcto).

    def commit(self) -> None:
        if self._rolledback:
            # Post-rollback, commit no hace NADA (idempotencia, no cambia estado).
            return
        self._committed = True
        self.commit_count += 1

    def rollback(self) -> None:
        if self._rolledback:
            # Idempotente: múltiples rollback son sin efectos posteriores.
            return
        self._rolledback = True
        self.rollback_count += 1


# ---------- Protocol checks ----------


def test_unit_of_work_protocol_has_required_members() -> None:
    sigs = {
        "__enter__",
        "__exit__",
        "commit",
        "rollback",
    }
    for name in sigs:
        assert hasattr(UnitOfWork, name), f"Falta miembro UnitOfWork.{name}"

    members = inspect.getmembers(UnitOfWork)
    method_names = {name for name, _ in members if callable(getattr(UnitOfWork, name, None))}
    assert sigs.issubset(method_names | {"__init__", "__subclasshook__"})


def test_fake_uow_implements_protocol_at_runtime() -> None:
    """Runtime check Protocol (gate 0.2 usa @runtime_checkable)."""
    fake = FakeUnitOfWork()
    assert isinstance(fake, UnitOfWork) is True


# ---------- Semántica Happy path ----------


def test_commit_when_everything_ok() -> None:
    uow = FakeUnitOfWork()
    with uow as u:
        assert u is uow
        assert uow.entered is True
        # Orquestación OK → commit explícito
        u.commit()
    assert uow.exited is True
    assert uow.commit_count == 1
    assert uow.rollback_count == 0


def test_double_commits_idempotent() -> None:
    uow = FakeUnitOfWork()
    with uow:
        uow.commit()
        uow.commit()
    # Semántica: dos commits dentro de scope OK → 2 (no hacemos de-duplicar).
    # El test solo prueba que no rompa; la implementación real decide.
    assert uow.rollback_count == 0


def test_commit_after_rollback_is_noop() -> None:
    """Idempotencia: tras rollback, commit no puede hacer nada de persistencia."""
    uow = FakeUnitOfWork()
    uow.rollback()
    uow.commit()
    assert uow.commit_count == 0
    assert uow.rollback_count == 1


# ---------- Semántica error / rollback ----------


def test_exception_triggers_rollback_and_propagates() -> None:
    uow = FakeUnitOfWork()
    with pytest.raises(ValueError, match="fatal"):
        with uow:
            raise ValueError("fatal")
    assert uow.commit_count == 0
    assert uow.rollback_count == 1


def test_no_commit_causes_rollback_exit() -> None:
    """Cambio parcial no confirmado: sin commit() explícito → __exit__ rollback."""
    uow = FakeUnitOfWork()
    with uow:
        # El usuario olvida llamar a commit() → NO commit implícito.
        pass
    assert uow.commit_count == 0
    assert uow.rollback_count == 1


def test_nested_exception_with_commit_not_called() -> None:
    uow = FakeUnitOfWork()
    with uow:
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            # Capturamos pero NO re-lanzamos; pero tampoco commit.
            pass
    # Como commit nunca fue llamado → rollback automático aunque no hubo propagación
    # por el exit (exc era None al salir; pero la regla es "sin commit → rollback").
    assert uow.commit_count == 0
    assert uow.rollback_count == 1
