"""Tests unitarios exhaustivos para Money / Currency (Decimal-only, sin whitelist)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from universal_business.domain.shared.errors import MoneyCurrencyMismatchError, MoneyRoundingError
from universal_business.domain.shared.value_objects.money import (
    MONEY_PRECISION,
    MONEY_ROUNDING,
    MONEY_SCALE,
    Currency,
    Money,
    is_supported_currency,
    list_supported_currencies,
)


# ---------- (10.B) Currency universal tests ----------
def test_currency_eur_valid() -> None:
    assert Currency("EUR").code == "EUR"


def test_currency_dop_valid() -> None:
    assert Currency("DOP").code == "DOP"


def test_currency_jpy_valid() -> None:
    assert Currency("JPY").code == "JPY"


def test_currency_mxn_valid() -> None:
    assert Currency("MXN").code == "MXN"


def test_currency_gbp_valid() -> None:
    assert Currency("GBP").code == "GBP"


def test_currency_chf_cop_also_valid_no_whitelist() -> None:
    # Aseguramos que NO exista whitelist: CHF, COP, ARS, BOB, CLP, PEN pasan.
    assert Currency("CHF").code == "CHF"
    assert Currency("COP").code == "COP"
    assert Currency("ARS").code == "ARS"


def test_currency_lowercase_normalizes_to_uppercase() -> None:
    assert Currency("eur").code == "EUR"
    assert Currency("Usd").code == "USD"
    assert Currency("  jpy  ").code == "JPY"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "AB",  # len < 3
        "ABCD",  # len > 3
        "123",  # dígitos
        "U D",  # espacios intermedios
        "US$",  # símbolos
        "pesos",  # palabra larga
        123,  # tipo erróneo
    ],
)
def test_currency_invalid_code_raises(bad: object) -> None:
    with pytest.raises(MoneyCurrencyMismatchError):
        Currency(bad)  # type: ignore[arg-type]


def test_currency_is_hashable_and_comparable() -> None:
    a = Currency("USD")
    b = Currency("usd")
    assert hash(a) == hash(b)
    assert a == b
    # Contra str (comparación flexible)
    assert a == "USD"
    assert "USD" == a  # type: ignore[comparison-overlap]
    s = {a, b, Currency("EUR")}
    assert len(s) == 2


# ---------- Money ----------
def test_money_policy_constants_sane() -> None:
    assert MONEY_PRECISION >= 10
    assert MONEY_SCALE == 4
    assert MONEY_ROUNDING == "ROUND_HALF_EVEN"


def test_money_rejects_float_in_ctor() -> None:
    with pytest.raises(MoneyCurrencyMismatchError):
        Money(3.14, "USD")  # type: ignore[arg-type]


def test_money_rejects_invalid_currency() -> None:
    with pytest.raises(MoneyCurrencyMismatchError):
        Money(1, "pesos")
    # "XXX" es 3 letras → PASSAHORA (sin whitelist). Usar inválidos:
    with pytest.raises(MoneyCurrencyMismatchError):
        Money(1, "USDD")
    with pytest.raises(MoneyCurrencyMismatchError):
        Money(1, "U")


def test_money_int_constructor() -> None:
    m = Money(5, "USD")
    assert m.amount == Decimal("5.0000")
    assert m.currency == Currency("USD")


def test_money_decimal_constructor_quantizes() -> None:
    m = Money(Decimal("1.123456"), "EUR")
    assert m.amount == Decimal("1.1235")  # ROUND_HALF_EVEN: 1.123456 ~ 1.1235


def test_money_constructor_from_str() -> None:
    m = Money("19.99", "DOP")
    assert m.amount == Decimal("19.9900")
    assert m.currency == Currency("DOP")


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
    assert c.currency == Currency("USD")


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
    assert z.currency == Currency("EUR")


def test_money_sum_works() -> None:
    items = [Money(i, "USD") for i in (1, 2, 3)]
    total = sum(items)  # type: ignore[arg-type]
    assert total.amount == Decimal("6.0000")


def test_money_hash_and_set() -> None:
    s = {Money(1, "USD"), Money(1, "USD"), Money(2, "USD")}
    assert len(s) == 2


def test_is_supported_currency_and_list() -> None:
    # Cualquier código 3 letras alfabéticas es soportado (sin whitelist).
    assert is_supported_currency("USD")
    assert is_supported_currency("MXN")
    assert is_supported_currency("JPY")
    # BTC es 3 letras alpha: soportado (host puede restringir en FASE 2+).
    assert is_supported_currency("BTC")
    # No 3 letras: no soportado.
    assert not is_supported_currency("US")
    assert not is_supported_currency("USDD")
    # list_supported_currencies retorna [] porque no hay whitelist cerrada;
    # es hook para hosts que decidan activar restricción.
    assert isinstance(list_supported_currencies(), list)


def test_money_accepts_currency_vo_in_ctor() -> None:
    c = Currency("MXN")
    m = Money(99, c)
    assert m.currency is c or m.currency == c
    assert m.amount == Decimal("99.0000")


def test_money_float_rejected_via_multiply_too() -> None:
    m = Money("10", "USD")
    with pytest.raises(MoneyCurrencyMismatchError):
        m * 1.5  # type: ignore[operator]
