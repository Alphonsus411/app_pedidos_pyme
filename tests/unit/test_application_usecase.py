"""Tests unitarios — UseCase execution pattern happy/sad/rollback/events post-commit."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pytest

from universal_business.application import (
    DomainEventDispatcher,
    EventPublisher,
    UnitOfWork,
    UseCaseHandler,
    execute_use_case,
)
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import (
    CustomerId,
    TenantId,
)

# ---------- Reutilizar los fakes de tests anteriores, los importamos como fixtures.
# Definimos clones aquí para que el test sea standalone sin cross-dependencies.


class _FakeUoW(UnitOfWork):  # type: ignore[misc]
    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0
        self._committed = False

    def __enter__(self) -> _FakeUoW:
        self._committed = False
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc is not None or not self._committed:
            self.rollback()

    def commit(self) -> None:
        if self.rollback_count > 0:
            return
        self.commit_count += 1
        self._committed = True

    def rollback(self) -> None:
        self.rollback_count += 1


class _FakeEventPublisher(EventPublisher):  # type: ignore[misc]
    def __init__(self) -> None:
        self.published: list[DomainEvent] = []

    def publish(self, event: DomainEvent, /) -> None:
        self.published.append(event)

    def publish_many(self, events, /) -> None:
        self.published.extend(list(events))


# ---------- Datos para tests ----------


@dataclass(frozen=True, kw_only=True)
class _DummyEventCreated(DomainEvent):
    aggregate_id: CustomerId
    aggregate_type: str = "Dummy"
    name: str = ""


def _event(name: str = "e1") -> _DummyEventCreated:
    return _DummyEventCreated(aggregate_id=CustomerId.generate(), name=name)


# ---------- UseCase handlers de prueba ----------


class _HappyPathUC(UseCaseHandler[dict, str]):
    """Orquestador ficticio happy path con 2 DomainEvent."""

    def handle(self, input: dict, /) -> tuple[str, Sequence[DomainEvent]]:
        ev1 = _event(input.get("name1", "e1"))
        ev2 = _event(input.get("name2", "e2"))
        return ("OK", [ev1, ev2])


class _ExplodingUC(UseCaseHandler[dict, str]):
    """Levanta ValueError antes de return."""

    def handle(self, input: dict, /) -> tuple[str, Sequence[DomainEvent]]:
        _ = _event("x")  # generar pero NO devolver (excepción lo corta).
        raise ValueError("fallo orquestación")


class _CommitExplodingUoW(_FakeUoW):
    """UoW donde el commit lanza RuntimeError (error en persistencia)."""

    def commit(self) -> None:
        raise RuntimeError("DB connection lost")


# ---------- Tests ----------


def test_usecase_protocol_runtime_checkable() -> None:
    assert isinstance(_HappyPathUC(), UseCaseHandler)


def test_happy_path_commits_dispatches_publishes_ordered() -> None:
    handler = _HappyPathUC()
    uow = _FakeUoW()
    disp = DomainEventDispatcher()
    rec: list[DomainEvent] = []

    class _H:
        def handle(self, event: DomainEvent) -> None:
            rec.append(event)

    disp.register(DomainEvent, _H())
    pub = _FakeEventPublisher()
    result = execute_use_case(
        handler=handler,
        input={"name1": "A", "name2": "B"},
        unit_of_work=uow,
        event_dispatcher=disp,
        event_publisher=pub,
    )
    assert result == "OK"
    assert uow.commit_count == 1
    assert uow.rollback_count == 0
    # Events recolectados.
    assert len(rec) == 2
    assert rec[0].name == "A"
    assert rec[1].name == "B"
    # Publisher recibió los mismos eventos en el mismo orden.
    assert [e.name for e in pub.published] == ["A", "B"]


def test_failure_handler_rollbacks_and_does_not_publish_events() -> None:
    handler = _ExplodingUC()
    uow = _FakeUoW()
    disp = DomainEventDispatcher()
    count_dispatched = []
    calls: list[int] = []

    class _Cnt:
        def handle(self, event: DomainEvent) -> None:  # type: ignore[override]
            calls.append(1)
            count_dispatched.append(event)

    disp.register(DomainEvent, _Cnt())
    pub = _FakeEventPublisher()
    with pytest.raises(ValueError, match="fallo orquestación"):
        execute_use_case(
            handler=handler,
            input={},
            unit_of_work=uow,
            event_dispatcher=disp,
            event_publisher=pub,
        )
    assert uow.commit_count == 0
    assert uow.rollback_count == 1
    assert calls == []
    assert pub.published == []


def test_failure_on_commit_triggers_rollback_and_no_publish() -> None:
    handler = _HappyPathUC()
    uow = _CommitExplodingUoW()
    disp = DomainEventDispatcher()
    pub = _FakeEventPublisher()
    calls: list[int] = []

    class _Cnt:
        def handle(self, event: DomainEvent) -> None:
            calls.append(1)

    disp.register(DomainEvent, _Cnt())
    with pytest.raises(RuntimeError, match="DB connection lost"):
        execute_use_case(
            handler=handler,
            input={},
            unit_of_work=uow,
            event_dispatcher=disp,
            event_publisher=pub,
        )
    # UoW no committeó; rollback por __exit__ al propagarse exc.
    assert uow.commit_count == 0  # commit lanzó exc, count en Fake no se incrementa.
    assert uow.rollback_count == 1
    # Eventos NO publicados.
    assert calls == []
    assert pub.published == []


def test_tenancy_explicit_input_no_contextvars() -> None:
    """Comprobar que el use case recibe tenant_id EXPLÍCITO (no por contexto)."""

    class _TenantAwareUC(UseCaseHandler[dict, str]):
        def handle(self, input: dict, /) -> tuple[str, Sequence[DomainEvent]]:
            tid = input.get("tenant_id")
            if not isinstance(tid, TenantId):
                raise TypeError("tenant_id obligatorio")
            ev = _DummyEventCreated(
                aggregate_id=CustomerId.generate(),
                aggregate_type="Customer",
                tenant_id=tid,
                name="ok",
            )
            return (str(tid.raw), [ev])

    handler = _TenantAwareUC()
    tid = TenantId.generate()
    uow = _FakeUoW()
    disp = DomainEventDispatcher()
    pub = _FakeEventPublisher()
    result = execute_use_case(
        handler=handler,
        input={"tenant_id": tid},
        unit_of_work=uow,
        event_dispatcher=disp,
        event_publisher=pub,
    )
    assert result == str(tid.raw)
    # Los DomainEvent producidos llevan tenant_id == input.
    assert pub.published[0].tenant_id == tid
