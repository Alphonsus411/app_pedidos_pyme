from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, localcontext
from uuid import uuid4

import pytest

from universal_business.domain.orders.line import OrderLine
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import OfferingId
from universal_business.domain.shared.value_objects.money import Money


@pytest.fixture
def line() -> OrderLine:
    return OrderLine(
        line_id=uuid4(),
        offering_id=OfferingId.generate(),
        name=" Servicio ",
        quantity=Decimal("2.5"),
        unit_price=Money("1.2345", "EUR"),
        discount=Money("0.5", "EUR"),
        tax=Money("0.3", "EUR"),
    )


def test_snapshot_and_calculation(line: OrderLine) -> None:
    assert line.name == "Servicio"
    assert line.subtotal == Money("3.0862", "EUR")
    assert line.total == Money("2.8862", "EUR")
    with pytest.raises(FrozenInstanceError):
        line.name = "Otro"  # type: ignore[misc]


def test_rounding_is_independent_of_caller_precision(line: OrderLine) -> None:
    with localcontext() as context:
        context.prec = 6
        assert line.total.amount == Decimal("2.8862")


@pytest.mark.parametrize(
    "quantity",
    [
        Decimal("0"),
        Decimal("-1"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("0.00001"),
        Decimal("1000000.0001"),
        1.0,
        True,
    ],
)
def test_invalid_quantity(line: OrderLine, quantity: object) -> None:
    with pytest.raises(InvariantViolationError):
        replace(line, quantity=quantity)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field,value",
    [
        ("unit_price", Money("-1", "EUR")),
        ("discount", Money("-1", "EUR")),
        ("tax", Money("-1", "EUR")),
        ("tax", Money("1", "USD")),
        ("discount", Money("3.0863", "EUR")),
        ("unit_price", None),
        ("name", "  "),
    ],
)
def test_invalid_line(line: OrderLine, field: str, value: object) -> None:
    with pytest.raises(InvariantViolationError):
        replace(line, **{field: value})


def test_zero_price_and_full_discount_are_allowed(line: OrderLine) -> None:
    free = replace(line, unit_price=Money(0, "EUR"), discount=Money(0, "EUR"))
    assert free.total == Money("0.3", "EUR")
    discounted = replace(line, discount=line.subtotal)
    assert discounted.total == line.tax


def test_quantity_trailing_zeroes_and_context(line: OrderLine) -> None:
    with localcontext() as context:
        context.prec = 3
        updated = replace(line, quantity=Decimal("1.00000"))
        assert updated.subtotal.amount == Decimal("1.2345")


def test_amount_over_limit_is_rejected(line: OrderLine) -> None:
    with localcontext() as context:
        context.prec = 40
        with pytest.raises(InvariantViolationError):
            replace(line, unit_price=Money("1000000000000000000000", "EUR"))
