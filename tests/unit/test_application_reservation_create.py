"""Creación idempotente de borradores con dobles transaccionales."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests.unit.test_application_catalog import FakeEventPublisher
from tests.unit.test_application_reservation_confirm import Customers, Ledger, LockedStore
from tests.unit.test_application_reservation_confirm import run as confirm
from universal_business.application.errors import ApplicationError, IdempotencyConflictError
from universal_business.application.events.dispatcher import DomainEventDispatcher
from universal_business.application.execution import execute_use_case
from universal_business.application.idempotency import IdempotencyKey, scoped_idempotency_key
from universal_business.application.request_digest import request_digest
from universal_business.application.reservations.commands import (
    ConfirmReservation,
    CreateReservation,
)
from universal_business.application.reservations.creation import CreateReservationHandler
from universal_business.application.unit_of_work import CommitNotAppliedError
from universal_business.domain.business.entities import Location
from universal_business.domain.business.value_objects import Address, LocationStatus, OperatingHours
from universal_business.domain.customers.entities import Customer
from universal_business.domain.reservations.conflicts import conflicting_reservation_ids
from universal_business.domain.reservations.events import ReservationCreated
from universal_business.domain.reservations.interval import ReservationInterval
from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.resources.entities import Resource
from universal_business.domain.resources.value_objects import ResourceStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CustomerId,
    LocationId,
    ReservationId,
    ResourceId,
    ResourceTypeId,
    TenantId,
)


class DraftTransaction:
    def __init__(self):
        self.rows = {}
        self.pending = None
        self.fail = None
        self.commit_count = 0
        self.save_count = 0

    def __enter__(self):
        self.pending = None
        return self

    def get(self, *, tenant_id, reservation_id):
        return self.rows.get(reservation_id)

    def save(self, reservation):
        self.save_count += 1
        self.pending = reservation

    def commit(self):
        if self.fail:
            raise self.fail
        if self.pending is not None:
            self.rows[self.pending.id] = self.pending
        self.commit_count += 1

    def __exit__(self, exc_type, exc, tb):
        if exc:
            self.pending = None


class FixedRepo:
    def __init__(self, value):
        self.value = value

    def get(self, **kwargs):
        return self.value


@pytest.fixture
def case():
    tid, bid, lid, rid, cid = (
        TenantId.generate(),
        BusinessId.generate(),
        LocationId.generate(),
        ResourceId.generate(),
        CustomerId.generate(),
    )
    start = datetime(2026, 10, 28, 10, tzinfo=UTC)
    cmd = CreateReservation(
        tenant_id=tid,
        business_id=bid,
        location_id=lid,
        resource_id=rid,
        customer_id=cid,
        reservation_id=ReservationId.generate(),
        interval=ReservationInterval(start, start + timedelta(hours=1)),
        idempotency_key=IdempotencyKey(value="create-res-001"),
        party_size=2,
    )
    location = Location(
        id=lid,
        tenant_id=tid,
        business_id=bid,
        name="Local",
        address=Address(country_code="ES"),
        timezone="Europe/Madrid",
        operating_hours=OperatingHours(),
        status=LocationStatus.OPEN,
    )
    resource = Resource(
        id=rid,
        tenant_id=tid,
        business_id=bid,
        location_id=lid,
        resource_type_id=ResourceTypeId.generate(),
        name="Sala",
        capacity=2,
    )
    customer = Customer(id=cid, tenant_id=tid, business_id=bid, given_name="A")
    tx, store = DraftTransaction(), LockedStore()
    locs, resources, customers = FixedRepo(location), FixedRepo(resource), Customers(customer)
    handler = CreateReservationHandler(
        reservations=tx, customers=customers, locations=locs, resources=resources, idempotency=store
    )
    return cmd, tx, store, locs, resources, customers, handler


def run(handler, tx, command, publisher):
    return execute_use_case(
        handler=handler,
        input=command,
        unit_of_work=tx,
        event_dispatcher=DomainEventDispatcher(),
        event_publisher=publisher,
    )


def scoped(command):
    return scoped_idempotency_key(
        business_id=command.business_id,
        operation=f"{type(command).__module__}.{type(command).__qualname__}",
        key=command.idempotency_key,
    )


def test_creation_replay_conflict_and_draft_does_not_block(case):
    cmd, tx, store, _, _, _, handler = case
    publisher = FakeEventPublisher()
    first = run(handler, tx, cmd, publisher)
    draft = tx.rows[cmd.reservation_id]
    assert draft.status == ReservationStatus.DRAFT
    assert len(publisher.published) == 1 and isinstance(publisher.published[0], ReservationCreated)
    assert run(handler, tx, cmd, publisher) == first
    assert tx.save_count == 1
    assert len(publisher.published) == 1
    assert (
        conflicting_reservation_ids(
            tenant_id=cmd.tenant_id,
            business_id=cmd.business_id,
            location_id=cmd.location_id,
            resource_id=cmd.resource_id,
            interval=cmd.interval,
            reservations=[draft],
        )
        == ()
    )
    with pytest.raises(IdempotencyConflictError):
        run(handler, tx, replace(cmd, notes="changed"), publisher)
    with pytest.raises(ApplicationError, match="ya existe"):
        run(
            handler,
            tx,
            replace(cmd, idempotency_key=IdempotencyKey(value="other-key-001")),
            publisher,
        )


@pytest.mark.parametrize(
    "invalid", ["location", "closed", "resource", "inactive", "capacity", "customer", "party"]
)
def test_reject_invalid_input_and_release(case, invalid):
    cmd, tx, store, locations, resources, customers, handler = case
    if invalid == "location":
        locations.value = replace(locations.value, business_id=BusinessId.generate())
    if invalid == "closed":
        locations.value = replace(locations.value, status=LocationStatus.CLOSED)
    if invalid == "resource":
        resources.value = replace(resources.value, location_id=LocationId.generate())
    if invalid == "inactive":
        resources.value = replace(resources.value, status=ResourceStatus.INACTIVE)
    if invalid == "capacity":
        cmd = replace(cmd, party_size=3)
    if invalid == "customer":
        customers.value = replace(customers.value, tenant_id=TenantId.generate())
    if invalid == "party":
        cmd = replace(cmd, party_size=0)
    publisher = FakeEventPublisher()
    with pytest.raises(ApplicationError):
        run(handler, tx, cmd, publisher)
    assert tx.rows == {} and publisher.published == []
    assert store.reserve(cmd.tenant_id, scoped(cmd), "retry")


@pytest.mark.parametrize(
    "error,released",
    [(CommitNotAppliedError("not applied"), True), (RuntimeError("unknown"), False)],
)
def test_commit_failure_reservation_key(case, error, released):
    cmd, tx, store, _, _, _, handler = case
    tx.fail = error
    publisher = FakeEventPublisher()
    with pytest.raises(type(error)):
        run(handler, tx, cmd, publisher)
    assert publisher.published == []
    assert store.reserve(cmd.tenant_id, scoped(cmd), "retry") is released


def test_create_then_confirm_with_separate_operation_key(case):
    cmd, tx, store, _, _, customers, handler = case
    run(handler, tx, cmd, FakeEventPublisher())
    ledger = Ledger()
    ledger.rows = dict(tx.rows)
    confirm_cmd = ConfirmReservation(
        tenant_id=cmd.tenant_id,
        business_id=cmd.business_id,
        location_id=cmd.location_id,
        reservation_id=cmd.reservation_id,
        idempotency_key=cmd.idempotency_key,
    )
    confirm(ledger, store, customers.value, confirm_cmd)
    assert ledger.rows[cmd.reservation_id].status == ReservationStatus.CONFIRMED


def test_datetime_digest_normalizes_equivalent_instants_and_rejects_naive(case):
    from dataclasses import dataclass

    cmd = case[0]

    @dataclass(frozen=True)
    class Request:
        time: datetime

    instant = cmd.interval.start
    assert request_digest(Request(instant)) == request_digest(
        Request(instant.astimezone(ZoneInfo("Europe/Madrid")))
    )
    with pytest.raises(ValueError, match="Naive"):
        request_digest(Request(datetime(2026, 1, 1)))
    assert request_digest(cmd) != request_digest(
        replace(
            cmd,
            interval=ReservationInterval(
                cmd.interval.start + timedelta(minutes=1), cmd.interval.end
            ),
        )
    )


def test_complete_failure_after_commit_keeps_key_and_emits_event(case):
    cmd, tx, store, _, _, _, handler = case
    publisher = FakeEventPublisher()

    def fail_complete(*args):
        raise RuntimeError("complete failed")

    store.complete = fail_complete
    with pytest.raises(RuntimeError, match="complete failed"):
        run(handler, tx, cmd, publisher)
    assert cmd.reservation_id in tx.rows
    assert len(publisher.published) == 1
    assert not store.reserve(cmd.tenant_id, scoped(cmd), "retry")
