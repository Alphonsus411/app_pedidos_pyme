"""Matriz completa de transiciones de reserva."""

import pytest

from universal_business.domain.reservations.lifecycle import (
    allowed_reservation_transitions,
    validate_reservation_transition,
)
from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.shared.errors import StatusTransitionError

EXPECTED = {
    ReservationStatus.DRAFT: {ReservationStatus.CONFIRMED, ReservationStatus.CANCELLED},
    ReservationStatus.CONFIRMED: {
        ReservationStatus.CHECKED_IN,
        ReservationStatus.CANCELLED,
        ReservationStatus.NO_SHOW,
    },
    ReservationStatus.CHECKED_IN: {ReservationStatus.COMPLETED},
    ReservationStatus.COMPLETED: set(),
    ReservationStatus.CANCELLED: set(),
    ReservationStatus.NO_SHOW: set(),
}


@pytest.mark.parametrize("source", list(ReservationStatus))
@pytest.mark.parametrize("target", list(ReservationStatus))
def test_transition_matrix(source, target):
    if target in EXPECTED[source]:
        assert validate_reservation_transition(source, target) is None
    else:
        with pytest.raises(StatusTransitionError):
            validate_reservation_transition(source, target)


@pytest.mark.parametrize("source", list(ReservationStatus))
def test_allowed_destinations_are_immutable_and_match_matrix(source):
    result = allowed_reservation_transitions(source)
    assert isinstance(result, frozenset)
    assert result == EXPECTED[source]


def test_untyped_status_is_rejected_even_when_string_matches():
    with pytest.raises(StatusTransitionError):
        validate_reservation_transition("draft", ReservationStatus.CONFIRMED)
    with pytest.raises(StatusTransitionError):
        validate_reservation_transition(ReservationStatus.DRAFT, "confirmed")


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (ReservationStatus.DRAFT, False),
        (ReservationStatus.CONFIRMED, True),
        (ReservationStatus.CHECKED_IN, True),
        (ReservationStatus.COMPLETED, True),
        (ReservationStatus.CANCELLED, False),
        (ReservationStatus.NO_SHOW, False),
    ],
)
def test_occupancy_by_status(status, expected):
    from universal_business.domain.reservations.lifecycle import reservation_occupies_interval

    assert reservation_occupies_interval(status) is expected


def test_occupancy_rejects_untyped_status():
    from universal_business.domain.reservations.lifecycle import reservation_occupies_interval

    with pytest.raises(StatusTransitionError):
        reservation_occupies_interval("confirmed")
