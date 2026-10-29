"""La preparación de eventos ocurre antes de confirmar la transacción."""

from collections.abc import Iterator, Sequence
from typing import Any
from unittest.mock import Mock

import pytest

from universal_business.application.execution import ExecutionHooks, execute_use_case
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import OrderId


class BrokenEvents(Sequence[DomainEvent]):
    def __getitem__(self, index: Any) -> Any:
        raise RuntimeError("events unavailable")

    def __len__(self) -> int:
        return 1

    def __iter__(self) -> Iterator[DomainEvent]:
        raise RuntimeError("events unavailable")


class Handler:
    def __init__(self, events: Sequence[DomainEvent]) -> None:
        self.events = events
        self.failed = Mock()
        self.succeeded = Mock()

    def handle(self, input: str) -> tuple[str, Sequence[DomainEvent]]:
        return input, self.events

    def build_hooks(self, input: str, result: str) -> ExecutionHooks[str]:
        return ExecutionHooks(on_failure=self.failed, on_success=self.succeeded)


@pytest.mark.parametrize("use_collector", [False, True])
def test_event_materialization_failure_rolls_back_before_commit(use_collector: bool) -> None:
    handler = Handler(BrokenEvents())
    uow = Mock()
    uow.__enter__ = Mock(return_value=uow)
    uow.__exit__ = Mock(return_value=False)
    dispatcher, publisher = Mock(), Mock()
    collector = (lambda result, events: events) if use_collector else None

    with pytest.raises(RuntimeError, match="events unavailable"):
        execute_use_case(
            handler=handler,
            input="ok",
            unit_of_work=uow,
            event_dispatcher=dispatcher,
            event_publisher=publisher,
            _collector_override=collector,
        )

    uow.commit.assert_not_called()
    assert uow.__exit__.call_args.args[0] is RuntimeError
    handler.failed.assert_called_once()
    handler.succeeded.assert_not_called()
    dispatcher.dispatch_many.assert_not_called()
    publisher.publish_many.assert_not_called()


def test_commit_cannot_change_event_sequence_to_be_published() -> None:
    event = DomainEvent(aggregate_id=OrderId.generate(), aggregate_type="Order")
    events = [event]
    handler = Handler(events)
    uow = Mock()
    uow.__enter__ = Mock(return_value=uow)
    uow.__exit__ = Mock(return_value=False)
    uow.commit.side_effect = events.clear
    dispatcher, publisher = Mock(), Mock()

    assert (
        execute_use_case(
            handler=handler,
            input="ok",
            unit_of_work=uow,
            event_dispatcher=dispatcher,
            event_publisher=publisher,
        )
        == "ok"
    )

    assert events == []
    handler.succeeded.assert_called_once_with("ok")
    dispatcher.dispatch_many.assert_called_once_with([event])
    publisher.publish_many.assert_called_once_with([event])
