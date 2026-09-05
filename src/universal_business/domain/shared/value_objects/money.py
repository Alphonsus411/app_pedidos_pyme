"""Money y Currency. Decimal-only. NO float permitido jamás.

Política fija:
- Precisión interna Decimal: 10 dígitos.
- Escala: 4 decimales.
- Redondeo: ROUND_HALF_EVEN ("Banker's rounding").
- Monedas permitidas: DOP, USD, EUR (whitelist; ampliar aquí si se requiere).
- Mezcla de monedas en add/subtract: SIEMPRE falla (sin auto-conversión).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, getcontext
from typing import Annotated, Final

from universal_business.domain.shared.errors import (
    MoneyCurrencyMismatchError,
    MoneyRoundingError,
)

# ---------- Política global ----------
MONEY_PRECISION: Final[int] = 10
MONEY_SCALE: Final[int] = 4
MONEY_ROUNDING: Final[str] = ROUND_HALF_EVEN
MONEY_ALLOWED_CURRENCIES: Final[frozenset[str]] = frozenset({"DOP", "USD", "EUR"})

if getcontext().prec < MONEY_PRECISION:  # pragma: no cover - init side-effect
    getcontext().prec = MONEY_PRECISION

_QUANT: Final[Decimal] = Decimal(f"1E-{MONEY_SCALE}")

CurrencyStr = Annotated[str, "ISO-4217 3 letras, mayúsculas"]

AmountInput = int | Decimal | str  # NO float


def _reject_float(value: object) -> None:
    if isinstance(value, float):
        raise MoneyCurrencyMismatchError(
            "Money NO acepta float. Usa Decimal(str(x)) o int para evitar errores de precisión."
        )


def _to_decimal(value: AmountInput) -> Decimal:
    """Coerción SEGURA. NO float."""
    _reject_float(value)
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            raise MoneyRoundingError("Money.amount str no puede ser vacío")
        try:
            return Decimal(s)
        except Exception as exc:  # noqa: BLE001 - Decimal lanza varios
            raise MoneyRoundingError(f"Money.amount str no es decimal válido: {value!r}") from exc
    raise TypeError(f"Money.amount tipo no soportado: {type(value).__name__}")


def _validate_currency(cur: str) -> str:
    if not isinstance(cur, str):
        raise MoneyCurrencyMismatchError(f"Moneda inválida: tipo {type(cur).__name__}")
    if len(cur) != 3 or not cur.isalpha():
        raise MoneyCurrencyMismatchError(f"Moneda inválida: {cur!r}. Esperado ISO-4217 3 letras.")
    cur = cur.upper()
    if MONEY_ALLOWED_CURRENCIES and cur not in MONEY_ALLOWED_CURRENCIES:
        raise MoneyCurrencyMismatchError(
            f"Moneda no permitida: {cur!r}. "
            f"Habilítala en MONEY_ALLOWED_CURRENCIES si corresponde. "
            f"Permitidas: {sorted(MONEY_ALLOWED_CURRENCIES)}"
        )
    return cur


@dataclass(frozen=True)
class Money:
    """Value object moneda. Inmutable. Decimal estricto.

    Operaciones:
    - add/subtract: mismo currency o falla.
    - multiply/divide: por int | Decimal | str (NO float).
    - compare: mismo currency o falla.
    """

    amount: Decimal
    currency: CurrencyStr

    def __init__(self, amount: AmountInput, currency: str) -> None:
        amt = _to_decimal(amount)
        cur = _validate_currency(currency)
        quantized = amt.quantize(_QUANT, rounding=MONEY_ROUNDING)
        object.__setattr__(self, "amount", quantized)
        object.__setattr__(self, "currency", cur)

    # ---------- Helpers constructivos ----------
    @classmethod
    def zero(cls, currency: str) -> Money:
        return cls(0, currency)

    @classmethod
    def of(cls, amount: AmountInput, currency: str) -> Money:
        return cls(amount, currency)

    # ---------- Validación currency compartida ----------
    def _same_currency_or_fail(self, other: Money) -> None:
        if self.currency != other.currency:
            raise MoneyCurrencyMismatchError(
                f"No se pueden combinar monedas distintas: {self.currency} vs {other.currency}"
            )

    # ---------- Aritmética ----------
    def add(self, other: Money) -> Money:
        self._same_currency_or_fail(other)
        return Money(self.amount + other.amount, self.currency)

    def __add__(self, other: Money) -> Money:
        return self.add(other)

    def __radd__(self, other: object) -> Money:
        if isinstance(other, int) and other == 0:
            # Útil para `sum(...)` que empieza en 0
            return self
        return NotImplemented

    def subtract(self, other: Money) -> Money:
        self._same_currency_or_fail(other)
        return Money(self.amount - other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        return self.subtract(other)

    def multiply(self, factor: AmountInput) -> Money:
        """Soporta precio×cantidad, impuestos %, descuentos %, tarifas, factores."""
        f = _to_decimal(factor)
        return Money(self.amount * f, self.currency)

    def __mul__(self, factor: AmountInput) -> Money:
        return self.multiply(factor)

    def __rmul__(self, factor: AmountInput) -> Money:
        return self.multiply(factor)

    def divide(self, divisor: AmountInput) -> Money:
        d = _to_decimal(divisor)
        if d == Decimal("0"):
            raise MoneyRoundingError("Money.divide por cero")
        return Money(self.amount / d, self.currency)

    def __truediv__(self, divisor: AmountInput) -> Money:
        return self.divide(divisor)

    # ---------- Comparación ----------
    def _cmp_check(self, other: Money) -> None:
        if not isinstance(other, Money):
            return NotImplemented
        self._same_currency_or_fail(other)

    def __lt__(self, other: Money) -> bool:
        self._same_currency_or_fail(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._same_currency_or_fail(other)
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._same_currency_or_fail(other)
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._same_currency_or_fail(other)
        return self.amount >= other.amount

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return False
        return self.currency == other.currency and self.amount == other.amount

    def __hash__(self) -> int:
        return hash((type(self).__name__, self.currency, self.amount))

    # ---------- Predicados ----------
    @property
    def is_zero(self) -> bool:
        return self.amount == Decimal("0")

    @property
    def is_positive(self) -> bool:
        return self.amount > Decimal("0")

    @property
    def is_negative(self) -> bool:
        return self.amount < Decimal("0")

    def __str__(self) -> str:
        return f"{self.amount:f} {self.currency}"

    def __repr__(self) -> str:
        return f"Money({self.amount:f}, {self.currency!r})"


# ---------- Currency helpers ----------
def is_supported_currency(code: str) -> bool:
    try:
        _validate_currency(code)
    except MoneyCurrencyMismatchError:
        return False
    return True


def list_supported_currencies() -> list[str]:
    return sorted(MONEY_ALLOWED_CURRENCIES)


__all__ = [
    "Money",
    "CurrencyStr",
    "AmountInput",
    "MONEY_PRECISION",
    "MONEY_SCALE",
    "MONEY_ROUNDING",
    "MONEY_ALLOWED_CURRENCIES",
    "is_supported_currency",
    "list_supported_currencies",
]
