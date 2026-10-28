"""Ejemplo transaccional simulado: no valida un adaptador de base de datos."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event, Lock

import pytest

from universal_business.domain.reservations.allocation import ReservationUnavailableError
from universal_business.domain.reservations.interval import ReservationInterval
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    ReservationId,
    ResourceId,
    TenantId,
)


class SimulatedLedger:
    """Almacén único con mutex; contiene solo el subconjunto de solapes del contrato."""

    def __init__(self):
        self.lock = Lock()
        self.confirmed = []


class SimulatedTransaction:
    """Protección retenida hasta commit/rollback, sin infraestructura real."""

    def __init__(self, ledger, scope):
        self.ledger, self.scope = ledger, scope
        self.held = False
        self.pending = None
        self.committed = False

    def __enter__(self):
        return self

    def protect_and_check(
        self,
        *,
        tenant_id,
        business_id,
        location_id,
        resource_id,
        reservation_id,
        interval,
        party_size,
    ):
        if (tenant_id, business_id, location_id, resource_id) != self.scope:
            raise ValueError("scope mismatch")
        self.ledger.lock.acquire()
        self.held = True
        if any(interval.overlaps(existing) for _, existing in self.ledger.confirmed):
            raise ReservationUnavailableError("resource occupied")

    def save_confirmed(self, reservation_id, interval):
        if not self.held:
            raise RuntimeError("transaction is not protected")
        self.pending = (reservation_id, interval)

    def commit(self):
        if self.pending is not None:
            self.ledger.confirmed.append(self.pending)
        self.committed = True

    def __exit__(self, exc_type, exc, tb):
        if not self.committed:
            self.pending = None
        if self.held:
            self.held = False
            self.ledger.lock.release()


@pytest.fixture
def inputs():
    scope = (
        TenantId.generate(),
        BusinessId.generate(),
        LocationId.generate(),
        ResourceId.generate(),
    )
    start = datetime(2026, 10, 28, 10, tzinfo=UTC)
    return scope, ReservationInterval(start, start + timedelta(hours=1))


def protect(transaction, scope, reservation_id, interval):
    transaction.protect_and_check(
        tenant_id=scope[0],
        business_id=scope[1],
        location_id=scope[2],
        resource_id=scope[3],
        reservation_id=reservation_id,
        interval=interval,
        party_size=1,
    )


def test_competing_transactions_serialize_and_only_one_commits(inputs):
    scope, interval = inputs
    ledger = SimulatedLedger()
    protected, second_started, release_first = Event(), Event(), Event()
    ids = [ReservationId.generate(), ReservationId.generate()]

    def first():
        with SimulatedTransaction(ledger, scope) as tx:
            protect(tx, scope, ids[0], interval)
            tx.save_confirmed(ids[0], interval)
            protected.set()
            if not release_first.wait(timeout=5):
                raise RuntimeError("synchronization timeout")
            tx.commit()

    def second():
        second_started.set()
        with SimulatedTransaction(ledger, scope) as tx:
            protect(tx, scope, ids[1], interval)
            tx.save_confirmed(ids[1], interval)
            tx.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(first)
        try:
            assert protected.wait(timeout=5)
            b = pool.submit(second)
            assert second_started.wait(timeout=5)
        finally:
            release_first.set()
        a.result(timeout=5)
        with pytest.raises(ReservationUnavailableError):
            b.result(timeout=5)
    assert ledger.confirmed == [(ids[0], interval)]


def test_rollback_discards_claim_and_allows_next_transaction(inputs):
    scope, interval = inputs
    ledger = SimulatedLedger()
    with pytest.raises(RuntimeError, match="abort"):
        with SimulatedTransaction(ledger, scope) as tx:
            protect(tx, scope, ReservationId.generate(), interval)
            tx.save_confirmed(ReservationId.generate(), interval)
            raise RuntimeError("abort")
    assert ledger.confirmed == []
    expected = ReservationId.generate()
    with SimulatedTransaction(ledger, scope) as tx:
        protect(tx, scope, expected, interval)
        tx.save_confirmed(expected, interval)
        tx.commit()
    assert ledger.confirmed == [(expected, interval)]


def test_scope_mismatch_fails_before_lock(inputs):
    scope, interval = inputs
    ledger = SimulatedLedger()
    wrong = (TenantId.generate(), *scope[1:])
    with pytest.raises(ValueError, match="scope mismatch"):
        with SimulatedTransaction(ledger, scope) as tx:
            protect(tx, wrong, ReservationId.generate(), interval)
    assert not ledger.lock.locked()
    assert ledger.confirmed == []
