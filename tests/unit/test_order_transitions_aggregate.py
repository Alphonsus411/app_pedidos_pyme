from dataclasses import replace

import pytest

from tests.unit.test_order_lines_aggregate import line as line
from tests.unit.test_order_lines_aggregate import order as order
from universal_business.domain.orders.entities import Order
from universal_business.domain.orders.line import OrderLine
from universal_business.domain.orders.value_objects import OrderStatus
from universal_business.domain.shared.errors import InvariantViolationError, StatusTransitionError
from universal_business.domain.shared.value_objects.money import Money


def test_valid_transitions_and_frozen_lines(order: Order, line: OrderLine) -> None:
    order.add_line(line)
    order.transition_to(OrderStatus.VALIDATED)
    with pytest.raises(InvariantViolationError):
        order.remove_line(line.line_id)
    order.transition_to(OrderStatus.CONFIRMED)
    order.transition_to(OrderStatus.COMPLETED)
    assert order.total == line.total
    assert order.lines == (line,)
    with pytest.raises(StatusTransitionError):
        order.transition_to(OrderStatus.DRAFT)


def test_confirmation_without_lines_fails_and_does_not_change_status(order: Order) -> None:
    order.transition_to(OrderStatus.VALIDATED)
    with pytest.raises(InvariantViolationError):
        order.transition_to(OrderStatus.CONFIRMED)
    assert order.status == OrderStatus.VALIDATED


def test_legacy_total_alone_is_not_confirmable(order: Order) -> None:
    legacy = replace(order, status=OrderStatus.VALIDATED, total=Money(5, "EUR"))
    with pytest.raises(InvariantViolationError):
        legacy.transition_to(OrderStatus.CONFIRMED)
    assert legacy.status == OrderStatus.VALIDATED


def test_return_to_draft_allows_editing(order: Order, line: OrderLine) -> None:
    order.add_line(line)
    order.transition_to(OrderStatus.VALIDATED)
    order.transition_to(OrderStatus.DRAFT)
    order.remove_line(line.line_id)
    assert order.total is None


@pytest.mark.parametrize(
    "name,value",
    [
        ("status", OrderStatus.CONFIRMED),
        ("lines", ()),
        ("total", None),
        ("_order_initialized", False),
    ],
)
def test_direct_assignment_and_deletion_rejected(order: Order, name: str, value: object) -> None:
    with pytest.raises(InvariantViolationError):
        setattr(order, name, value)
    with pytest.raises(InvariantViolationError):
        delattr(order, name)


def test_invalid_transitions_do_not_modify_state(order: Order) -> None:
    with pytest.raises(StatusTransitionError):
        order.transition_to(OrderStatus.COMPLETED)
    assert order.status == OrderStatus.DRAFT


def test_rehydrate_legacy_confirmed_order(order: Order) -> None:
    legacy = replace(order, status=OrderStatus.CONFIRMED, total=Money(5, "EUR"))
    legacy.transition_to(OrderStatus.COMPLETED)
    assert legacy.total == Money(5, "EUR")
