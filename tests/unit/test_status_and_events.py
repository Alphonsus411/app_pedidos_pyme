"""Tests unitarios para primitivas de status + DomainEvent."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

import pytest

from universal_business.domain.shared.errors import (
    InvariantViolationError,
    StatusTransitionError,
    TimezoneAwareRequiredError,
)
from universal_business.domain.shared.events import AggregateRootMixin, DomainEvent
from universal_business.domain.shared.value_objects.ids import (
    CustomerId,
    DomainEventId,
    TenantId,
)
from universal_business.domain.shared.value_objects.status import StatusTransition, transition_guard


class TrafficLight(StrEnum):
    RED = "red"
    YELLOW = "yellow"
    GREEN = "green"


FSM: dict[TrafficLight, set[TrafficLight]] = {
    TrafficLight.RED: {TrafficLight.GREEN},
    TrafficLight.GREEN: {TrafficLight.YELLOW},
    TrafficLight.YELLOW: {TrafficLight.RED},
}


def test_status_transition_can_ensure() -> None:
    s = StatusTransition(FSM)
    assert s.can(TrafficLight.RED, TrafficLight.GREEN)
    assert not s.can(TrafficLight.RED, TrafficLight.YELLOW)
    s.ensure(TrafficLight.RED, TrafficLight.GREEN)
    with pytest.raises(StatusTransitionError):
        s.ensure(TrafficLight.RED, TrafficLight.YELLOW)


def test_transition_guard_functional() -> None:
    transition_guard(TrafficLight.GREEN, TrafficLight.YELLOW, FSM)
    with pytest.raises(StatusTransitionError):
        transition_guard(TrafficLight.GREEN, TrafficLight.RED, FSM)


def test_domain_event_mandatory_fields_aware() -> None:
    tid = TenantId.generate()
    ev = DomainEvent(aggregate_id=tid, aggregate_type="Tenant")
    assert isinstance(ev.event_id, DomainEventId)
    assert ev.aggregate_id is tid
    assert ev.aggregate_type == "Tenant"
    assert ev.occurred_at.tzinfo is not None


def test_domain_event_rejects_naive_datetime() -> None:
    tid = TenantId.generate()
    naive = dt.datetime(2025, 1, 1, 12, 0)
    with pytest.raises(TimezoneAwareRequiredError):
        DomainEvent(
            event_id=DomainEventId.generate(),
            occurred_at=naive,  # type: ignore[arg-type]
            aggregate_id=tid,
            aggregate_type="Tenant",
        )


def test_domain_event_rejects_bad_aggregate_type() -> None:
    tid = TenantId.generate()
    with pytest.raises(InvariantViolationError):
        DomainEvent(aggregate_id=tid, aggregate_type="X")


def test_domain_event_occurred_at_utc() -> None:
    z5 = dt.timezone(dt.timedelta(hours=5))
    tid = TenantId.generate()
    ev = DomainEvent(
        aggregate_id=tid,
        aggregate_type="Tenant",
        occurred_at=dt.datetime(2025, 1, 1, 12, 0, tzinfo=z5),
    )
    assert ev.occurred_at_utc.hour == 7


def test_aggregate_root_mixin_collects_events() -> None:
    class Dummy(AggregateRootMixin):
        pass

    d = Dummy()
    cid = CustomerId.generate()
    e1 = DomainEvent(aggregate_id=cid, aggregate_type="Customer")
    d.add_domain_event(e1)
    assert len(d.domain_events) == 1
    # Añadir el mismo evento por id (igual event_id) no duplica
    d.add_domain_event(e1)
    assert len(d.domain_events) == 1
    d.clear_domain_events()
    assert d.domain_events == []


def test_aggregate_root_mixin_rejects_non_event() -> None:
    class Dummy(AggregateRootMixin):
        pass

    d = Dummy()
    with pytest.raises(InvariantViolationError):
        d.add_domain_event("not an event")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# DomainEvent.metadata: INMUTABILIDAD SEMÁNTICA (Hardening Gate 0.1-RC1)
# ---------------------------------------------------------------------------


def test_domain_event_metadata_built_from_dict_is_readable() -> None:
    tid = TenantId.generate()
    md = {"source": "web", "version": 2}
    ev = DomainEvent(aggregate_id=tid, aggregate_type="Tenant", metadata=md)
    assert ev.metadata["source"] == "web"
    assert ev.metadata["version"] == 2
    assert "source" in ev.metadata
    assert list(ev.metadata.keys()) == ["source", "version"]


def test_domain_event_metadata_default_is_empty_immutable() -> None:
    tid = TenantId.generate()
    ev = DomainEvent(aggregate_id=tid, aggregate_type="Tenant")
    assert len(ev.metadata) == 0
    # Asignación por clave debe fallar (MappingProxyType).
    with pytest.raises(TypeError):
        ev.metadata["x"] = 1  # type: ignore[index]


def test_domain_event_metadata_cannot_be_mutated_after_construction() -> None:
    tid = TenantId.generate()
    ev = DomainEvent(
        aggregate_id=tid,
        aggregate_type="Tenant",
        metadata={"a": 1, "b": ["x"]},
    )
    with pytest.raises(TypeError):
        ev.metadata["c"] = 3  # type: ignore[index]
    with pytest.raises(TypeError):
        del ev.metadata["a"]  # type: ignore[attr-defined]
    with pytest.raises((TypeError, AttributeError)):
        ev.metadata.update({"c": 3})  # type: ignore[union-attr]


def test_domain_event_metadata_original_dict_mutation_does_not_affect_event() -> None:
    """Copia defensiva: el dict original pasado a metadata no modifica el evento."""
    tid = TenantId.generate()
    original: dict[str, object] = {"k": "initial"}
    ev = DomainEvent(aggregate_id=tid, aggregate_type="Tenant", metadata=original)
    original["k"] = "MUTATED"
    original["extra"] = 42
    assert ev.metadata["k"] == "initial"
    assert "extra" not in ev.metadata
