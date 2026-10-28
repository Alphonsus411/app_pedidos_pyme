from dataclasses import replace
from decimal import Decimal, localcontext
from uuid import uuid4

import pytest

from universal_business.domain.orders.entities import Order
from universal_business.domain.orders.line import OrderLine
from universal_business.domain.orders.value_objects import OrderChannel, OrderStatus
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    OfferingId,
    OrderId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money


@pytest.fixture
def order() -> Order:
    return Order(
        id=OrderId.generate(),
        tenant_id=TenantId.generate(),
        business_id=BusinessId.generate(),
        location_id=LocationId.generate(),
        status=OrderStatus.DRAFT,
        channel=OrderChannel.WEB,
    )


@pytest.fixture
def line() -> OrderLine:
    return OrderLine(
        line_id=uuid4(),
        offering_id=OfferingId.generate(),
        name="Producto",
        quantity=Decimal("2"),
        unit_price=Money("10", "EUR"),
        discount=Money("1", "EUR"),
        tax=Money("2", "EUR"),
    )


def test_add_remove_and_calculate(order: Order, line: OrderLine) -> None:
    second = replace(line, line_id=uuid4(), quantity=Decimal("1"))
    order.add_line(line)
    order.add_line(second)
    assert order.lines == (line, second)
    assert order.total == Money("32", "EUR")
    order.remove_line(line.line_id)
    assert order.total == Money("11", "EUR")
    order.remove_line(second.line_id)
    assert order.lines == ()
    assert order.total is None


def test_rehydration_recalculates_and_rejects_incorrect_total(
    order: Order, line: OrderLine
) -> None:
    assert replace(order, lines=(line,)).total == line.total
    with pytest.raises(InvariantViolationError):
        replace(order, lines=(line,), total=Money("1", "EUR"))


def test_duplicate_and_mixed_currency_rejected_without_mutation(
    order: Order, line: OrderLine
) -> None:
    order.add_line(line)
    other = replace(
        line,
        line_id=uuid4(),
        unit_price=Money(10, "USD"),
        discount=Money(1, "USD"),
        tax=Money(2, "USD"),
    )
    for invalid in (line, other):
        with pytest.raises(InvariantViolationError):
            order.add_line(invalid)
        assert order.lines == (line,)
        assert order.total == line.total


@pytest.mark.parametrize("status", [s for s in OrderStatus if s != OrderStatus.DRAFT])
def test_lines_frozen_outside_draft(order: Order, line: OrderLine, status: OrderStatus) -> None:
    order.add_line(line)
    order = replace(order, status=status)
    with pytest.raises(InvariantViolationError):
        order.add_line(replace(line, line_id=uuid4()))
    with pytest.raises(InvariantViolationError):
        order.remove_line(line.line_id)
    assert order.lines == (line,)


def test_missing_line_and_invalid_container(order: Order, line: OrderLine) -> None:
    with pytest.raises(InvariantViolationError):
        order.remove_line(uuid4())
    with pytest.raises(InvariantViolationError):
        replace(order, lines=[line])  # type: ignore[arg-type]


def test_total_independent_of_callers_decimal_context(order: Order, line: OrderLine) -> None:
    with localcontext() as context:
        context.prec = 3
        order.add_line(line)
        assert order.total is not None
        assert order.total.amount == Decimal("21.0000")


def test_limit_and_bad_line_rejected(order: Order, line: OrderLine) -> None:
    many = tuple(replace(line, line_id=uuid4()) for _ in range(1001))
    with pytest.raises(InvariantViolationError):
        replace(order, lines=many)
    with pytest.raises(InvariantViolationError):
        order.add_line(None)  # type: ignore[arg-type]
    assert order.lines == ()
    assert order.total is None
