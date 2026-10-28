"""Pruebas exhaustivas de la matriz de pedidos."""

import pytest

from universal_business.domain.orders.lifecycle import (
    allowed_order_transitions,
    validate_order_transition,
)
from universal_business.domain.orders.value_objects import OrderStatus
from universal_business.domain.shared.errors import StatusTransitionError

EXPECTED = {
    OrderStatus.DRAFT: {OrderStatus.VALIDATED, OrderStatus.CANCELLED},
    OrderStatus.VALIDATED: {OrderStatus.DRAFT, OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.PREPARING, OrderStatus.COMPLETED, OrderStatus.CANCELLED},
    OrderStatus.PREPARING: {OrderStatus.READY, OrderStatus.CANCELLED},
    OrderStatus.READY: {OrderStatus.DELIVERING, OrderStatus.COMPLETED, OrderStatus.CANCELLED},
    OrderStatus.DELIVERING: {OrderStatus.COMPLETED, OrderStatus.CANCELLED},
    OrderStatus.COMPLETED: set(),
    OrderStatus.CANCELLED: set(),
}


@pytest.mark.parametrize("source", list(OrderStatus))
@pytest.mark.parametrize("target", list(OrderStatus))
def test_all_transitions(source: OrderStatus, target: OrderStatus) -> None:
    assert allowed_order_transitions(source) == EXPECTED[source]
    if target in EXPECTED[source]:
        validate_order_transition(source, target)
    else:
        with pytest.raises(StatusTransitionError):
            validate_order_transition(source, target)


@pytest.mark.parametrize("invalid", [None, "draft", 0, True])
def test_invalid_types_are_rejected(invalid: object) -> None:
    with pytest.raises(StatusTransitionError):
        allowed_order_transitions(invalid)  # type: ignore[arg-type]
    with pytest.raises(StatusTransitionError):
        validate_order_transition(OrderStatus.DRAFT, invalid)  # type: ignore[arg-type]


def test_destinations_are_immutable() -> None:
    assert isinstance(allowed_order_transitions(OrderStatus.DRAFT), frozenset)
