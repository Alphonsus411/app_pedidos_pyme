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
