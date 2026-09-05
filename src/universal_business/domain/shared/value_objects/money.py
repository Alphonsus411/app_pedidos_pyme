"""Money y Currency. Decimal-only. NO float permitido jamás.

Política fija:
- Precisión interna Decimal: 10 dígitos.
- Escala: 4 decimales.
- Redondeo: ROUND_HALF_EVEN ("Banker's rounding").
- Currency: value object inmutable, ISO-4217-like 3 letras alfabéticas, SIN whitelist cerrada
  (acepta EUR, USD, DOP, JPY, MXN, GBP, COP, CHF, … cualquier código 3 letras;
  validación estricta contra el catálogo ISO-4217 completo queda como extensión futura
  configurable por el host, no como hardcode del Universal Business Core).
- Mezcla de monedas en add/subtract: SIEMPRE falla (sin auto-conversión).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, getcontext
from typing import Final

from universal_business.domain.shared.errors import (
    MoneyCurrencyMismatchError,
    MoneyRoundingError,
)

# ---------- Política global ----------
MONEY_PRECISION: Final[int] = 10
MONEY_SCALE: Final[int] = 4
MONEY_ROUNDING: Final[str] = ROUND_HALF_EVEN

if getcontext().prec < MONEY_PRECISION:  # pragma: no cover - init side-effect
    getcontext().prec = MONEY_PRECISION

_QUANT: Final[Decimal] = Decimal(f"1E-{MONEY_SCALE}")

_CURRENCY_CODE_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z]{3}$")

AmountInput = int | Decimal | str  # NO float


# ---------- Currency (value object real) ----------
@dataclass(frozen=True, repr=False)
class Currency:
    """Value Object moneda. Inmutable, hashable, sin whitelist cerrada.

    Reglas de construcción:
    - 3 letras alfabéticas (Regex ISO-4217-like).
    - Normalización a uppercase.
    - str, Currency se aceptan (Currency no cambia si ya es uppercase 3 letras).
    """

    code: str

    def __init__(self, value: str | Currency) -> None:
        if isinstance(value, Currency):
            object.__setattr__(self, "code", value.code)
            return
        if not isinstance(value, str):
            raise MoneyCurrencyMismatchError(
                f"Currency debe ser str o Currency: {type(value).__name__}"
            )
        s = value.strip()
        if not _CURRENCY_CODE_RE.fullmatch(s):
            raise MoneyCurrencyMismatchError(
                f"Código de moneda inválido: {value!r}. "
                "Esperado código ISO-4217-like de 3 letras alfabéticas."
            )
        object.__setattr__(self, "code", s.upper())

    @classmethod
    def of(cls, value: str | Currency) -> Currency:
        return cls(value)

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"Currency({self.code!r})"

    def __hash__(self) -> int:
        return hash(("Currency", self.code))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Currency):
            return self.code == other.code
        if isinstance(other, str):
            return self.code == Currency(other).code
        return NotImplemented


# ---------- Validación / coerción Money helpers ----------
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


# ---------- Money ----------
@dataclass(frozen=True)
class Money:
    """Value object cantidad monetaria. Inmutable. Decimal estricto.

    Operaciones:
    - add/subtract: mismo currency o falla.
    - multiply/divide: por int | Decimal | str (NO float).
    - compare: mismo currency o falla.
    """

    amount: Decimal
    currency: Currency

    def __init__(self, amount: AmountInput, currency: str | Currency) -> None:
        amt = _to_decimal(amount)
        cur = currency if isinstance(currency, Currency) else Currency(currency)
        quantized = amt.quantize(_QUANT, rounding=MONEY_ROUNDING)
        object.__setattr__(self, "amount", quantized)
        object.__setattr__(self, "currency", cur)

    # ---------- Helpers constructivos ----------
    @classmethod
    def zero(cls, currency: str | Currency) -> Money:
        return cls(0, currency)

    @classmethod
    def of(cls, amount: AmountInput, currency: str | Currency) -> Money:
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
        return f"Money({self.amount:f}, Currency({self.currency.code!r}))"


# ---------- Currency helpers ----------
def is_supported_currency(code: str) -> bool:
    """Devuelve True si el código es 3 letras alfabéticas (ISO-4217-like).

    Sin whitelist geográfica cerrada.
    """
    try:
        Currency(code)
    except MoneyCurrencyMismatchError:
        return False
    return True


def list_supported_currencies() -> list[str]:
    """Retorna lista vacía: no hay whitelist cerrada.

    Esta función queda como hook para configuraciones host futuras
    que decidan restringir a un subconjunto ISO-4217.
    """
    return []


__all__ = [
    "Money",
    "Currency",
    "AmountInput",
    "MONEY_PRECISION",
    "MONEY_SCALE",
    "MONEY_ROUNDING",
    "is_supported_currency",
    "list_supported_currencies",
]
