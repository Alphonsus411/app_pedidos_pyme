"""Tests unitarios — contracts mínimos messaging + errores de aplicación (Gate 0.2)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass

import pytest

from universal_business.application import (
    ApplicationError,
    Command,
    CommandHandler,
    HandlerNotFoundError,
    IdempotencyConflictError,
    Query,
    QueryHandler,
)
from universal_business.domain.shared.value_objects.ids import TenantId

# ---------- Command ----------


@dataclass(frozen=True, kw_only=True)
class _FakeCommand(Command):
    tenant_id: TenantId
    value: str = "hola"


def test_command_is_frozen_immutable() -> None:
    tid = TenantId.generate()
    cmd = _FakeCommand(tenant_id=tid)
    with pytest.raises(FrozenInstanceError):
        cmd.value = "otro"  # type: ignore[attr-defined]
    assert cmd.tenant_id == tid
    assert cmd.value == "hola"


def test_command_kw_only_requires_explicit_field_names() -> None:
    tid = TenantId.generate()
    with pytest.raises(TypeError):
        # NO se permite invocación posicional
        _FakeCommand(tid)  # type: ignore[call-arg]
    cmd = _FakeCommand(tenant_id=tid, value="ok")
    assert cmd.value == "ok"


# ---------- Query ----------


@dataclass(frozen=True, kw_only=True)
class _FakeQuery(Query):
    tenant_id: TenantId
    limit: int = 10


def test_query_is_frozen_immutable() -> None:
    tid = TenantId.generate()
    q = _FakeQuery(tenant_id=tid, limit=20)
    with pytest.raises(FrozenInstanceError):
        q.limit = 50  # type: ignore[attr-defined]
    assert q.limit == 20


# ---------- Handlers ----------


class _FakeCommandHandler(CommandHandler[_FakeCommand, str]):
    def handle(self, command: _FakeCommand) -> str:
        return f"processed:{command.value}"


class _FakeQueryHandler(QueryHandler[_FakeQuery, list[int]]):
    def handle(self, query: _FakeQuery) -> list[int]:
        return list(range(query.limit))


def test_command_handler_runs_and_returns_result() -> None:
    tid = TenantId.generate()
    h = _FakeCommandHandler()
    result = h.handle(_FakeCommand(tenant_id=tid, value="abc"))
    assert result == "processed:abc"


def test_command_handler_protocol_runtime_checkable() -> None:
    h = _FakeCommandHandler()
    assert isinstance(h, CommandHandler) is True


def test_query_handler_runs_and_returns_result() -> None:
    tid = TenantId.generate()
    h = _FakeQueryHandler()
    result = h.handle(_FakeQuery(tenant_id=tid, limit=3))
    assert result == [0, 1, 2]


def test_query_handler_protocol_runtime_checkable() -> None:
    h = _FakeQueryHandler()
    assert isinstance(h, QueryHandler) is True


# ---------- Errores ----------


def test_application_error_hierarchy_matches_domain() -> None:
    with pytest.raises(ApplicationError):
        raise ApplicationError("fallo aplicación")


def test_handler_not_found_extends_application() -> None:
    assert issubclass(HandlerNotFoundError, ApplicationError)


def test_idempotency_conflict_extends_application() -> None:
    assert issubclass(IdempotencyConflictError, ApplicationError)
    with pytest.raises(IdempotencyConflictError):
        raise IdempotencyConflictError("ya procesado")
