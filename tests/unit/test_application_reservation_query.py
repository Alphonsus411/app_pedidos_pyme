from dataclasses import FrozenInstanceError, replace

import pytest

from tests.unit.test_application_reservation_confirm import case as case
from universal_business.application.errors import ApplicationError
from universal_business.application.reservations.queries import GetReservation
from universal_business.application.reservations.query_handlers import GetReservationHandler
from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    ReservationId,
    TenantId,
)


class Repo:
    def __init__(self, value):
        self.value, self.calls = value, []

    def get(self, *, tenant_id, reservation_id):
        self.calls.append((tenant_id, reservation_id))
        return self.value


def setup(case):
    ledger, _, _, cmd = case
    query = GetReservation(
        tenant_id=cmd.tenant_id,
        business_id=cmd.business_id,
        location_id=cmd.location_id,
        reservation_id=cmd.reservation_id,
    )
    return query, ledger.rows[cmd.reservation_id]


def test_view_is_immutable_and_does_not_change_with_aggregate(case):
    query, reservation = setup(case)
    repo = Repo(reservation)
    view = GetReservationHandler(reservations=repo).handle(query)
    assert view is not None and view.resource_id == reservation.resource_id
    assert repo.calls == [(query.tenant_id, query.reservation_id)]
    with pytest.raises(FrozenInstanceError):
        view.status = ReservationStatus.CANCELLED
    old_status = view.status
    reservation.status = ReservationStatus.CANCELLED
    assert view.status == old_status


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", TenantId.generate()),
        ("business_id", BusinessId.generate()),
        ("location_id", LocationId.generate()),
        ("id", ReservationId.generate()),
    ],
)
def test_out_of_scope_is_indistinguishable_from_absent(case, field, value):
    query, reservation = setup(case)
    assert (
        GetReservationHandler(reservations=Repo(replace(reservation, **{field: value}))).handle(
            query
        )
        is None
    )
    assert GetReservationHandler(reservations=Repo(None)).handle(query) is None


def test_invalid_scope_fails_before_repository_access(case):
    query, reservation = setup(case)
    repo = Repo(reservation)
    with pytest.raises(ApplicationError):
        GetReservationHandler(reservations=repo).handle(replace(query, tenant_id=None))
    assert not repo.calls
