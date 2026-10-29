"""Semántica de entrega; los dobles no prueban un adaptador durable."""

from unittest.mock import Mock, call

import pytest

from universal_business.application.events.outbox_delivery import (
    ClaimedOutboxEvent,
    OutboxDeliveryWorker,
)
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import OrderId


@pytest.fixture
def event() -> DomainEvent:
    return DomainEvent(aggregate_id=OrderId.generate(), aggregate_type="Order")


def test_empty_outbox_does_not_publish_or_acknowledge() -> None:
    store, publisher = Mock(), Mock()
    store.claim_one.return_value = None
    assert not OutboxDeliveryWorker(store=store, publisher=publisher).process_one()
    publisher.publish.assert_not_called()
    store.mark_delivered.assert_not_called()


def test_publish_before_acknowledgement_with_same_event_and_token(event: DomainEvent) -> None:
    store, publisher = Mock(), Mock()
    timeline = Mock()
    timeline.attach_mock(publisher, "publisher")
    timeline.attach_mock(store, "store")
    store.claim_one.return_value = ClaimedOutboxEvent(event=event, claim_token="lease-1")
    assert OutboxDeliveryWorker(store=store, publisher=publisher).process_one()
    assert timeline.mock_calls == [
        call.store.claim_one(),
        call.publisher.publish(event),
        call.store.mark_delivered(event.event_id, "lease-1"),
    ]


def test_publish_failure_never_marks_delivery(event: DomainEvent) -> None:
    store, publisher = Mock(), Mock()
    store.claim_one.return_value = ClaimedOutboxEvent(event=event, claim_token="lease-1")
    publisher.publish.side_effect = RuntimeError("publisher unavailable")
    with pytest.raises(RuntimeError, match="publisher unavailable"):
        OutboxDeliveryWorker(store=store, publisher=publisher).process_one()
    store.mark_delivered.assert_not_called()


def test_ack_failure_propagates_and_retry_can_publish_duplicate(event: DomainEvent) -> None:
    store, publisher = Mock(), Mock()
    store.claim_one.side_effect = [
        ClaimedOutboxEvent(event=event, claim_token="lease-1"),
        ClaimedOutboxEvent(event=event, claim_token="lease-2"),
    ]
    store.mark_delivered.side_effect = [RuntimeError("lost claim"), None]
    worker = OutboxDeliveryWorker(store=store, publisher=publisher)
    with pytest.raises(RuntimeError, match="lost claim"):
        worker.process_one()
    assert worker.process_one()
    assert publisher.publish.call_count == 2
    assert store.mark_delivered.call_args_list[0].args == (event.event_id, "lease-1")
    assert store.mark_delivered.call_args_list[1].args == (event.event_id, "lease-2")


@pytest.mark.parametrize("token", ["", "  "])
def test_claim_rejects_blank_token(event: DomainEvent, token: str) -> None:
    with pytest.raises(ValueError, match="token"):
        ClaimedOutboxEvent(event=event, claim_token=token)
