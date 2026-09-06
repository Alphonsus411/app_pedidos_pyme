"""Tests unitarios — DomainEvent Dispatcher interno síncrono + EventPublisher port."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from universal_business.application.errors import ApplicationError
from universal_business.application.events import (
    DomainEventDispatcher,
    DomainEventHandler,
    EventPublisher,
)
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import (
    CustomerId,
    OrderId,
)

# ---------- Fixtures: DomainEvent subtipos para tests ----------


@dataclass(frozen=True, kw_only=True)
class _CustomerCreated(DomainEvent):
    aggregate_id: CustomerId
    aggregate_type: str = "Customer"

    display_name: str = ""


@dataclass(frozen=True, kw_only=True)
class _OrderCreated(DomainEvent):
    aggregate_id: OrderId
    aggregate_type: str = "Order"
    total_cents: int = 0


class _RecordingHandler(DomainEventHandler[DomainEvent]):
    """Handler que solo guarda eventos en una lista."""

    def __init__(self, tag: str = "default") -> None:
        self.received: list[tuple[str, DomainEvent]] = []
        self.tag = tag
        self.call_count = 0

    def handle(self, event: DomainEvent) -> None:
        self.call_count += 1
        self.received.append((self.tag, event))


class _ExplodingHandler(DomainEventHandler[DomainEvent]):
    """Handler que lanza ValueError al recibir un evento. Útil para semántica de error."""

    def __init__(self, exc: BaseException | None = None) -> None:
        self.exc = exc or ValueError("boom handler")

    def handle(self, event: DomainEvent) -> None:
        raise self.exc


# ---------- FakeEventPublisher ----------


class FakeEventPublisher(EventPublisher):
    """EventPublisher in-memory para tests. SOLO para testing."""

    def __init__(self) -> None:
        self.published: list[DomainEvent] = []
        self.batch_count = 0
        self.single_count = 0

    def publish(self, event: DomainEvent, /) -> None:
        self.single_count += 1
        self.published.append(event)

    def publish_many(self, events, /) -> None:
        self.batch_count += 1
        # Materializamos (como la especificación sugiere).
        for e in list(events):
            self.published.append(e)


# ---------- Helpers ----------


def _make_customer_event(name: str = "Ana") -> _CustomerCreated:
    return _CustomerCreated(aggregate_id=CustomerId.generate(), display_name=name)


def _make_order_event(total: int = 1000) -> _OrderCreated:
    return _OrderCreated(aggregate_id=OrderId.generate(), total_cents=total)


# ---------- DomainEventHandler Protocol check ----------


def test_recording_handler_is_event_handler_at_runtime() -> None:
    assert isinstance(_RecordingHandler(), DomainEventHandler) is True


def test_fake_event_publisher_is_protocol_at_runtime() -> None:
    assert isinstance(FakeEventPublisher(), EventPublisher) is True


# ---------- Dispatcher: registro / dispatch 1 a 1 ----------


def test_one_event_one_handler() -> None:
    d = DomainEventDispatcher()
    h = _RecordingHandler(tag="cc")
    d.register(_CustomerCreated, h)
    ev = _make_customer_event()
    d.dispatch(ev)
    assert h.call_count == 1
    assert h.received[0] == ("cc", ev)


def test_one_event_multiple_handlers_order_preserved() -> None:
    d = DomainEventDispatcher()
    h_a = _RecordingHandler("A")
    h_b = _RecordingHandler("B")
    h_c = _RecordingHandler("C")
    d.register(_CustomerCreated, h_a)
    d.register(_CustomerCreated, h_b)
    d.register(_CustomerCreated, h_c)
    ev = _make_customer_event()
    d.dispatch(ev)
    assert [t for t, _ in h_a.received + h_b.received + h_c.received] == ["A", "B", "C"]
    assert h_a.call_count == 1
    assert h_b.call_count == 1
    assert h_c.call_count == 1


def test_no_handlers_is_noop_not_error() -> None:
    d = DomainEventDispatcher()
    ev = _make_customer_event()
    # Sin handlers → NO debe lanzar error.
    d.dispatch(ev)
    d.dispatch_many([ev])


def test_mro_resolves_superclass_handlers_to_all_events() -> None:
    """Handlers de DomainEvent genérico se disparan para TODO evento."""
    d = DomainEventDispatcher()
    generic = _RecordingHandler(tag="ALL")
    specific = _RecordingHandler(tag="Order")
    d.register(DomainEvent, generic)
    d.register(_OrderCreated, specific)
    d.dispatch(_make_customer_event())
    d.dispatch(_make_order_event())
    # generic recibe ambos eventos (2 invocaciones); specific solo 1 Order.
    assert generic.call_count == 2
    assert specific.call_count == 1


# ---------- Dispatcher: dispatch_many ----------


def test_dispatch_many_order_matches_input() -> None:
    d = DomainEventDispatcher()
    rec = _RecordingHandler(tag="E")
    d.register(DomainEvent, rec)
    e1 = _make_customer_event("X")
    e2 = _make_order_event(99)
    e3 = _make_customer_event("Y")
    d.dispatch_many([e1, e2, e3])
    assert rec.call_count == 3
    assert [ev for (_, ev) in rec.received] == [e1, e2, e3]


def test_dispatch_many_rejects_non_domain_event_elements_before_any_handler() -> None:
    d = DomainEventDispatcher()
    calls: list[int] = []
    h = _RecordingHandler("A")

    def side_effect(event: DomainEvent) -> None:
        calls.append(1)
        h.handle(event)

    class _SEH:
        def handle(self, event: DomainEvent) -> None:
            side_effect(event)

    d.register(DomainEvent, _SEH())
    bad_list: list[object] = [_make_customer_event(), "ESTO NO ES UN EVENTO", _make_order_event()]
    with pytest.raises(ApplicationError, match="elemento #1"):
        d.dispatch_many(bad_list)  # type: ignore[arg-type]
    # Como la validación es eager ANTES de llamar a cualquier handler, calls debe estar vacío.
    assert calls == []


def test_dispatch_single_rejects_non_domain_event_type() -> None:
    d = DomainEventDispatcher()
    with pytest.raises(ApplicationError, match="argumento no es DomainEvent"):
        d.dispatch("not-an-event")  # type: ignore[arg-type]


# ---------- Dispatcher: handler exceptions propagate ----------


def test_handler_exception_propagates_no_silenced() -> None:
    d = DomainEventDispatcher()
    d.register(_CustomerCreated, _ExplodingHandler(ValueError("handler broke")))
    with pytest.raises(ValueError, match="handler broke"):
        d.dispatch(_make_customer_event())


def test_register_rejects_non_domainevent_subclass_as_type() -> None:
    d = DomainEventDispatcher()
    with pytest.raises(ApplicationError, match="event_type debe ser una subclase"):
        d.register(str, _RecordingHandler())  # type: ignore[arg-type]


# ---------- EventPublisher: happy paths ----------


def test_fake_publisher_receives_publish_single() -> None:
    p = FakeEventPublisher()
    e1 = _make_customer_event()
    p.publish(e1)
    assert p.single_count == 1
    assert p.published == [e1]


def test_fake_publisher_publish_many_stores_ordered() -> None:
    p = FakeEventPublisher()
    e1 = _make_customer_event("A")
    e2 = _make_order_event(42)
    p.publish_many([e1, e2])
    assert p.batch_count == 1
    assert p.published == [e1, e2]
