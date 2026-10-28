from dataclasses import FrozenInstanceError

import pytest

from tests.unit.test_order_lines_aggregate import line as line
from tests.unit.test_order_lines_aggregate import order as order
from universal_business.domain.orders.entities import Order
from universal_business.domain.orders.events import OrderStatusChanged
from universal_business.domain.orders.line import OrderLine
from universal_business.domain.orders.value_objects import OrderStatus
from universal_business.domain.shared.errors import InvariantViolationError, StatusTransitionError


def test_each_transition_records_an_immutable_event(order: Order, line: OrderLine) -> None:
    order.add_line(line)
    order.transition_to(OrderStatus.VALIDATED)
    order.transition_to(OrderStatus.CONFIRMED)
    first, second = order.domain_events
    assert isinstance(first, OrderStatusChanged)
    assert isinstance(second, OrderStatusChanged)
    assert first.aggregate_id == order.id
    assert first.tenant_id == order.tenant_id
    assert first.business_id == order.business_id
    assert first.location_id == order.location_id
    assert (first.previous_status, first.new_status) == (OrderStatus.DRAFT, OrderStatus.VALIDATED)
    assert (second.previous_status, second.new_status) == (
        OrderStatus.VALIDATED,
        OrderStatus.CONFIRMED,
    )
    assert first.event_id != second.event_id
    with pytest.raises(FrozenInstanceError):
        first.new_status = OrderStatus.CANCELLED  # type: ignore[misc]
    order.clear_domain_events()
    assert not order.domain_events


def test_failed_or_repeated_transition_records_no_event(order: Order) -> None:
    with pytest.raises(StatusTransitionError):
        order.transition_to(OrderStatus.DRAFT)
    with pytest.raises(StatusTransitionError):
        order.transition_to(OrderStatus.CONFIRMED)
    assert not order.domain_events
    order.transition_to(OrderStatus.VALIDATED)
    order.clear_domain_events()
    with pytest.raises(InvariantViolationError):
        order.transition_to(OrderStatus.CONFIRMED)
    assert not order.domain_events
    assert order.status == OrderStatus.VALIDATED


def test_events_are_isolated_between_orders(order: Order) -> None:
    from dataclasses import replace

    other = replace(order)
    order.transition_to(OrderStatus.CANCELLED)
    assert len(order.domain_events) == 1
    assert not other.domain_events
