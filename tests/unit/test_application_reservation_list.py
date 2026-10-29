from dataclasses import replace

import pytest

from tests.unit.test_application_reservation_confirm import case as case
from tests.unit.test_application_reservation_query import setup
from universal_business.application.errors import ApplicationError
from universal_business.application.reservations.queries import ListReservationsByLocation
from universal_business.application.reservations.query_handlers import (
    ListReservationsByLocationHandler,
)
from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.shared.value_objects.ids import BusinessId, LocationId, TenantId


class Reader:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def list_by_location(self, **kwargs):
        self.calls.append(kwargs)
        return self.rows


def query_for(case):
    get, reservation = setup(case)
    query = ListReservationsByLocation(
        tenant_id=get.tenant_id,
        business_id=get.business_id,
        location_id=get.location_id,
        status=reservation.status,
        limit=5,
    )
    return query, reservation


def test_list_returns_snapshot_and_forwards_scope(case):
    query, reservation = query_for(case)
    reader = Reader([reservation])
    views = ListReservationsByLocationHandler(reader=reader).handle(query)
    assert len(views) == 1 and views[0].reservation_id == reservation.id
    assert reader.calls == [
        dict(
            tenant_id=query.tenant_id,
            business_id=query.business_id,
            location_id=query.location_id,
            status=query.status,
            limit=5,
        )
    ]
    old = views[0].status
    reservation.status = ReservationStatus.CANCELLED
    assert views[0].status == old


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", TenantId.generate()),
        ("business_id", BusinessId.generate()),
        ("location_id", LocationId.generate()),
        ("status", ReservationStatus.NO_SHOW),
    ],
)
def test_wrong_scope_or_state_fails_without_partial_response(case, field, value):
    query, reservation = query_for(case)
    reader = Reader([reservation, replace(reservation, **{field: value})])
    with pytest.raises(ApplicationError):
        ListReservationsByLocationHandler(reader=reader).handle(query)


@pytest.mark.parametrize(
    "field,value",
    [
        ("limit", 0),
        ("limit", 101),
        ("limit", True),
        ("limit", 1.5),
        ("status", "draft"),
        ("business_id", None),
    ],
)
def test_invalid_query_does_not_read(case, field, value):
    query, reservation = query_for(case)
    reader = Reader([reservation])
    with pytest.raises(ApplicationError):
        ListReservationsByLocationHandler(reader=reader).handle(replace(query, **{field: value}))
    assert not reader.calls


def test_limit_duplicates_and_empty(case):
    query, reservation = query_for(case)
    with pytest.raises(ApplicationError):
        ListReservationsByLocationHandler(reader=Reader([reservation, reservation])).handle(
            replace(query, limit=1)
        )
    with pytest.raises(ApplicationError):
        ListReservationsByLocationHandler(reader=Reader([reservation, reservation])).handle(query)
    assert ListReservationsByLocationHandler(reader=Reader([])).handle(query) == ()
