"""Tests unitarios exhaustivos para Money / Currency (Decimal-only)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from universal_business.domain.shared.errors import MoneyCurrencyMismatchError, MoneyRoundingError
from universal_business.domain.shared.value_objects.money import (
    MONEY_ALLOWED_CURRENCIES,
    MONEY_PRECISION,
    MONEY_ROUNDING,
    MONEY_SCALE,
    Money,
    is_supported_currency,
    list_supported_currencies,
)


def test_money_policy_constants_sane() -> None:
    assert MONEY_PRECISION >= 10
    assert MONEY_SCALE == 4
    assert MONEY_ROUNDING == "ROUND_HALF_EVEN"
    assert {"DOP", "USD", "EUR"}.issubset(MONEY_ALLOWED_CURRENCIES)


def test_money_rejects_float_in_ctor() -> None:
    with pytest.raises(MoneyCurrencyMismatchError):
        Money(3.14, "USD")  # type: ignore[arg-type]


def test_money_rejects_invalid_currency() -> None:
    with pytest.raises(MoneyCurrencyMismatchError):
        Money(1, "pesos")
    with pytest.raises(MoneyCurrencyMismatchError):
        Money(1, "XXX")


def test_money_int_constructor() -> None:
    m = Money(5, "USD")
    assert m.amount == Decimal("5.0000")
    assert m.currency == "USD"


def test_money_decimal_constructor_quantizes() -> None:
    m = Money(Decimal("1.123456"), "EUR")
    assert m.amount == Decimal("1.1235")  # ROUND_HALF_EVEN: 1.123456 ~ 1.1235


def test_money_constructor_from_str() -> None:
    m = Money("19.99", "DOP")
    assert m.amount == Decimal("19.9900")
    assert m.currency == "DOP"


def test_money_invalid_str_amount() -> None:
    with pytest.raises(MoneyRoundingError):
        Money("abc", "USD")
    with pytest.raises(MoneyRoundingError):
        Money("", "USD")


def test_money_add_same_currency() -> None:
    a = Money("10.00", "USD")
    b = Money("20.50", "USD")
    c = a + b
    assert c.amount == Decimal("30.5000")
    assert c.currency == "USD"


def test_money_subtract_same_currency() -> None:
    a = Money("10", "EUR")
    b = Money("1", "EUR")
    assert (a - b).amount == Decimal("9.0000")


def test_money_mix_currencies_raises() -> None:
    a = Money(1, "USD")
    b = Money(1, "EUR")
    with pytest.raises(MoneyCurrencyMismatchError):
        a.add(b)
    with pytest.raises(MoneyCurrencyMismatchError):
        _ = a < b  # type: ignore[operator]
    with pytest.raises(MoneyCurrencyMismatchError):
        a + b


def test_money_multiply_by_int() -> None:
    m = Money("10.00", "USD") * 3
    assert m.amount == Decimal("30.0000")
    assert 3 * Money("10", "USD") == m


def test_money_multiply_by_decimal() -> None:
    price = Money("100.00", "DOP")
    tax = price * Decimal("0.18")  # ITBIS 18%
    assert tax.amount == Decimal("18.0000")
    total = price + tax
    assert total.amount == Decimal("118.0000")


def test_money_multiply_by_str() -> None:
    m = Money("100", "USD").multiply("1.07")
    assert m.amount == Decimal("107.0000")


def test_money_divide_by_decimal() -> None:
    m = Money("100", "USD").divide(Decimal("3"))
    # 100 / 3 = 33.33333... cuantizado a 33.3333 (4 decims, HALF_EVEN)
    assert m.amount == Decimal("33.3333")


def test_money_divide_by_zero_raises() -> None:
    with pytest.raises(MoneyRoundingError):
        Money(1, "USD").divide(0)


def test_money_comparison() -> None:
    a = Money("10", "USD")
    b = Money("20", "USD")
    c = Money("10", "USD")
    assert a < b
    assert b > a
    assert a <= c
    assert a >= c
    assert a == c
    assert a != b


def test_money_predicates() -> None:
    assert Money.zero("USD").is_zero
    assert not Money("1", "USD").is_zero
    assert Money("-1", "EUR").is_negative
    assert Money("0.01", "DOP").is_positive


def test_money_zero_helper() -> None:
    z = Money.zero("EUR")
    assert z.amount == Decimal("0.0000")
    assert z.currency == "EUR"


def test_money_sum_works() -> None:
    items = [Money(i, "USD") for i in (1, 2, 3)]
    total = sum(items)  # type: ignore[arg-type]
    assert total.amount == Decimal("6.0000")


def test_money_hash_and_set() -> None:
    s = {Money(1, "USD"), Money(1, "USD"), Money(2, "USD")}
    assert len(s) == 2


def test_is_supported_currency_and_list() -> None:
    assert is_supported_currency("USD")
    assert not is_supported_currency("BTC")
    assert "USD" in list_supported_currencies()
