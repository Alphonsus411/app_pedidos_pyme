"""Flujo integrado con fakes: no garantiza aislamiento ni durabilidad reales."""

from datetime import timedelta

import pytest

from tests.unit.test_application_catalog import FakeEventPublisher
from tests.unit.test_application_reservation_cancel import GuardedTransaction
from tests.unit.test_application_reservation_confirm import Ledger, Transaction
from tests.unit.test_application_reservation_create import case as case
from tests.unit.test_application_reservation_create import run
from universal_business.application.errors import ApplicationError
from universal_business.application.reservations.commands import (
    CheckInReservation,
    CompleteReservation,
    ConfirmReservation,
    MarkReservationNoShow,
)
from universal_business.application.reservations.creation import CreateReservationHandler
from universal_business.application.reservations.handlers import ConfirmReservationHandler
from universal_business.application.reservations.queries import GetReservation
from universal_business.application.reservations.query_handlers import GetReservationHandler
from universal_business.application.reservations.status_change import (
    CheckInReservationHandler,
    CompleteReservationHandler,
    MarkReservationNoShowHandler,
)
from universal_business.application.reservations.timing_policies import ReservationTimingPolicies
from universal_business.domain.reservations.events import (
    ReservationConfirmed,
    ReservationCreated,
    ReservationStatusChanged,
)
from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.shared.errors import StatusTransitionError


class DraftSession(Transaction):
    """Permite preparar la creación antes de obtener protección de recurso."""

    def __enter__(self):
        self.pending = None
        return self

    def save(self, reservation):
        self.pending = reservation


class StatusSession(GuardedTransaction):
    def __enter__(self):
        self.pending = None
        return self


@pytest.mark.parametrize("path", ["arrival", "no_show"])
def test_create_confirm_and_temporal_paths_with_replay(case, path):
    cmd, _, store, locations, resources, customers, _ = case
    ledger, publisher = Ledger(), FakeEventPublisher()
    create_tx = DraftSession(ledger)
    create = CreateReservationHandler(
        reservations=create_tx,
        customers=customers,
        locations=locations,
        resources=resources,
        idempotency=store,
    )
    initial = run(create, create_tx, cmd, publisher)
    assert ledger.rows[cmd.reservation_id].status == ReservationStatus.DRAFT
    scope = dict(
        tenant_id=cmd.tenant_id,
        business_id=cmd.business_id,
        location_id=cmd.location_id,
        reservation_id=cmd.reservation_id,
        idempotency_key=cmd.idempotency_key,
    )
    confirm_cmd = ConfirmReservation(**scope)
    confirm_tx = Transaction(ledger)
    confirm = ConfirmReservationHandler(
        reservations=confirm_tx, customers=customers, allocation=confirm_tx, idempotency=store
    )
    run(confirm, confirm_tx, confirm_cmd, publisher)
    assert ledger.rows[cmd.reservation_id].status == ReservationStatus.CONFIRMED
    clock = [cmd.interval.start]
    policies = ReservationTimingPolicies(
        clock=lambda: clock[0],
        early=timedelta(minutes=10),
        late=timedelta(minutes=5),
        grace_period=timedelta(minutes=8),
    )
    status_tx = StatusSession(ledger)
    arrival = CheckInReservationHandler(
        reservations=status_tx,
        guard=status_tx,
        idempotency=store,
        check_in_policy=policies.check_in,
    )
    no_show = MarkReservationNoShowHandler(
        reservations=status_tx, guard=status_tx, idempotency=store, no_show_policy=policies.no_show
    )
    arrival_cmd, absent_cmd = CheckInReservation(**scope), MarkReservationNoShow(**scope)
    if path == "arrival":
        checked = run(arrival, status_tx, arrival_cmd, publisher)
        assert checked.status == ReservationStatus.CHECKED_IN
        clock[0] = cmd.interval.start + timedelta(minutes=8)
        with pytest.raises(StatusTransitionError):
            run(no_show, status_tx, absent_cmd, publisher)
        completion = CompleteReservationHandler(
            reservations=status_tx, guard=status_tx, idempotency=store
        )
        run(completion, status_tx, CompleteReservation(**scope), publisher)
        expected = ReservationStatus.COMPLETED
        assert run(arrival, status_tx, arrival_cmd, publisher) == checked
    else:
        with pytest.raises(ApplicationError, match="no aprobada"):
            run(no_show, status_tx, absent_cmd, publisher)
        clock[0] = cmd.interval.start + timedelta(minutes=8)
        absent = run(no_show, status_tx, absent_cmd, publisher)
        with pytest.raises(StatusTransitionError):
            run(arrival, status_tx, arrival_cmd, publisher)
        expected = ReservationStatus.NO_SHOW
        assert run(no_show, status_tx, absent_cmd, publisher) == absent
    assert run(create, create_tx, cmd, publisher) == initial
    query = GetReservation(
        tenant_id=cmd.tenant_id,
        business_id=cmd.business_id,
        location_id=cmd.location_id,
        reservation_id=cmd.reservation_id,
    )
    view = GetReservationHandler(reservations=Transaction(ledger)).handle(query)
    assert view is not None and view.status == expected
    assert [type(event) for event in publisher.published] == (
        [
            ReservationCreated,
            ReservationConfirmed,
            ReservationStatusChanged,
            ReservationStatusChanged,
        ]
        if path == "arrival"
        else [ReservationCreated, ReservationConfirmed, ReservationStatusChanged]
    )
