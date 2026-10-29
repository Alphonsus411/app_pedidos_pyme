"""Concurrencia y recuperación de adjudicaciones experimentales SQLite."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest

from universal_business.application.events.outbox_delivery import OutboxDeliveryWorker
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import DomainEventId, OrderId
from universal_business.infrastructure.sqlite_outbox import (
    LostOutboxClaimError,
    SqliteOutboxDeliveryStore,
    SqliteOutboxWriter,
    create_sqlite_delivery_schema,
    create_sqlite_outbox_schema,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "delivery.db"
    with sqlite3.connect(path) as connection:
        create_sqlite_outbox_schema(connection)
        create_sqlite_delivery_schema(connection)
    return path


@pytest.fixture
def event() -> DomainEvent:
    return DomainEvent(aggregate_id=OrderId.generate(), aggregate_type="Order")


def insert_event(path: Path, event: DomainEvent) -> None:
    encoder = Mock()
    encoder.encode.return_value = b"encoded-event"
    with sqlite3.connect(path) as connection:
        connection.execute("BEGIN")
        SqliteOutboxWriter(connection=connection, encoder=encoder).write_many([event])


def make_store(path: Path, event: DomainEvent, clock: Mock) -> SqliteOutboxDeliveryStore:
    decoder = Mock()
    decoder.decode.return_value = event
    return SqliteOutboxDeliveryStore(
        connect=lambda: sqlite3.connect(path, timeout=5),
        decoder=decoder,
        lease_seconds=10,
        clock=clock,
    )


def test_concurrent_claims_are_exclusive(db_path: Path, event: DomainEvent) -> None:
    insert_event(db_path, event)
    store = make_store(db_path, event, Mock(return_value=100.0))
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: store.claim_one(), range(2)))
    assert sum(claim is not None for claim in claims) == 1


def test_expiry_reassigns_and_rejects_old_token(db_path: Path, event: DomainEvent) -> None:
    insert_event(db_path, event)
    clock = Mock(return_value=100.0)
    store = make_store(db_path, event, clock)
    first = store.claim_one()
    assert first is not None
    assert store.claim_one() is None
    clock.return_value = 110.0
    with pytest.raises(LostOutboxClaimError):
        store.mark_delivered(event.event_id, first.claim_token)
    second = store.claim_one()
    assert second is not None and second.claim_token != first.claim_token
    with pytest.raises(LostOutboxClaimError):
        store.mark_delivered(event.event_id, first.claim_token)
    store.mark_delivered(event.event_id, second.claim_token)
    assert store.claim_one() is None


def test_worker_publishes_and_marks_event(db_path: Path, event: DomainEvent) -> None:
    insert_event(db_path, event)
    store = make_store(db_path, event, Mock(return_value=100.0))
    publisher = Mock()
    worker = OutboxDeliveryWorker(store=store, publisher=publisher)
    assert worker.process_one()
    assert not worker.process_one()
    publisher.publish.assert_called_once_with(event)


def test_invalid_payload_does_not_claim_row(db_path: Path, event: DomainEvent) -> None:
    insert_event(db_path, event)
    wrong = DomainEvent(aggregate_id=OrderId.generate(), aggregate_type="Order")
    store = make_store(db_path, wrong, Mock(return_value=100.0))
    with pytest.raises(ValueError, match="no coincide"):
        store.claim_one()
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT * FROM outbox_delivery").fetchall() == []


def test_worker_retries_after_publication_failure(db_path: Path, event: DomainEvent) -> None:
    insert_event(db_path, event)
    clock = Mock(return_value=100.0)
    store = make_store(db_path, event, clock)
    publisher = Mock()
    publisher.publish.side_effect = [RuntimeError("failed"), None]
    worker = OutboxDeliveryWorker(store=store, publisher=publisher)
    with pytest.raises(RuntimeError, match="failed"):
        worker.process_one()
    assert not worker.process_one()
    clock.return_value = 110.0
    assert worker.process_one()
    assert publisher.publish.call_count == 2


def test_lease_starts_after_slow_decoding(db_path: Path, event: DomainEvent) -> None:
    insert_event(db_path, event)
    clock = Mock(return_value=100.0)
    decoder = Mock()

    def decode(payload: bytes) -> DomainEvent:
        clock.return_value = 120.0
        return event

    decoder.decode.side_effect = decode
    store = SqliteOutboxDeliveryStore(
        connect=lambda: sqlite3.connect(db_path), decoder=decoder, lease_seconds=10, clock=clock
    )
    claim = store.claim_one()
    assert claim is not None
    store.mark_delivered(event.event_id, claim.claim_token)


def test_manual_quarantine_unblocks_queue_and_requeue_keeps_payload(
    db_path: Path, event: DomainEvent
) -> None:
    bad_id = DomainEventId.generate()
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO transactional_outbox (event_id, payload) VALUES (?, ?)",
            (str(bad_id), b"corrupt"),
        )
    insert_event(db_path, event)
    decoder = Mock()
    decoder.decode.side_effect = lambda payload: event if payload == b"encoded-event" else None
    store = SqliteOutboxDeliveryStore(
        connect=lambda: sqlite3.connect(db_path),
        decoder=decoder,
        lease_seconds=10,
        clock=Mock(return_value=100.0),
    )
    with pytest.raises(ValueError, match="no coincide"):
        store.claim_one()
    store.quarantine(bad_id, "payload no reconocido")
    worker = OutboxDeliveryWorker(store=store, publisher=Mock())
    assert worker.process_one()
    assert not worker.process_one()
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT payload FROM transactional_outbox WHERE event_id = ?", (str(bad_id),)
        ).fetchone() == (b"corrupt",)
    store.requeue(bad_id)
    with pytest.raises(ValueError, match="no coincide"):
        store.claim_one()


def test_quarantine_rejects_active_and_delivered_events(db_path: Path, event: DomainEvent) -> None:
    insert_event(db_path, event)
    store = make_store(db_path, event, Mock(return_value=100.0))
    claim = store.claim_one()
    assert claim is not None
    with pytest.raises(ValueError, match="adjudicación vigente"):
        store.quarantine(event.event_id, "motivo")
    store.mark_delivered(event.event_id, claim.claim_token)
    with pytest.raises(ValueError, match="entregado"):
        store.quarantine(event.event_id, "motivo")


def test_quarantine_and_requeue_validate_requests(db_path: Path, event: DomainEvent) -> None:
    store = make_store(db_path, event, Mock(return_value=100.0))
    with pytest.raises(ValueError, match="motivo"):
        store.quarantine(event.event_id, " ")
    with pytest.raises(ValueError, match="no encontrado"):
        store.quarantine(event.event_id, "motivo")
    with pytest.raises(ValueError, match="no está en cuarentena"):
        store.requeue(event.event_id)


def test_existing_delivery_schema_can_add_quarantine_without_losing_events(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        create_sqlite_outbox_schema(connection)
        connection.execute(
            "CREATE TABLE outbox_delivery (event_id TEXT PRIMARY KEY, token TEXT, "
            "expires_at REAL, delivered INTEGER NOT NULL DEFAULT 0)"
        )
        connection.execute(
            "INSERT INTO transactional_outbox (event_id, payload) VALUES (?, ?)",
            ("existing", b"original"),
        )
        create_sqlite_delivery_schema(connection)
        create_sqlite_delivery_schema(connection)
        assert connection.execute(
            "SELECT event_id, payload FROM transactional_outbox"
        ).fetchall() == [("existing", b"original")]
        assert connection.execute("SELECT * FROM outbox_quarantine").fetchall() == []
