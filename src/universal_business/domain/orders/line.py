"""Snapshot inmutable y cálculo explícito de una línea de pedido.

Esta política interna no representa una factura ni una regla fiscal.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from uuid import UUID

from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import OfferingId
from universal_business.domain.shared.value_objects.money import Money


@dataclass(frozen=True, kw_only=True)
class OrderLine:
    """Precio y nombre capturados; descuento e impuesto son importes por línea.

    Se redondea el subtotal a cuatro decimales con la política Money, luego
    se resta el descuento y se añade el impuesto. Cantidades de hasta un millón
    y cuatro decimales; se exige precio explícito, incluido cero cuando proceda.
    Cada importe de entrada debe ser menor que 10²¹ unidades de su moneda.
    """

    line_id: UUID
    offering_id: OfferingId
    name: str
    quantity: Decimal
    unit_price: Money
    discount: Money
    tax: Money

    def __post_init__(self) -> None:
        if not isinstance(self.line_id, UUID) or not isinstance(self.offering_id, OfferingId):
            raise InvariantViolationError("Identificadores de línea u oferta inválidos")
        if not isinstance(self.name, str) or not self.name.strip():
            raise InvariantViolationError("El nombre de la línea no puede estar vacío")
        object.__setattr__(self, "name", self.name.strip())
        if not isinstance(self.quantity, Decimal) or not self.quantity.is_finite():
            raise InvariantViolationError("La cantidad debe ser Decimal finito")
        if not Decimal(0) < self.quantity <= Decimal(1000000):
            raise InvariantViolationError("Cantidad fuera de los límites permitidos")
        parts = self.quantity.as_tuple()
        exponent = parts.exponent
        assert isinstance(exponent, int)  # Finite Decimal, verified above.
        digits = parts.digits
        while digits and digits[-1] == 0:
            exponent += 1
            digits = digits[:-1]
        if exponent < -4:
            raise InvariantViolationError("La cantidad admite hasta cuatro decimales")
        for amount in (self.unit_price, self.discount, self.tax):
            if not isinstance(amount, Money) or not amount.amount.is_finite():
                raise InvariantViolationError("Los importes deben ser Money finitos")
            if amount.amount < 0:
                raise InvariantViolationError("Los importes no pueden ser negativos")
            if amount.amount.adjusted() > 20:
                raise InvariantViolationError("Importe superior al límite interno de la línea")
            if amount.currency != self.unit_price.currency:
                raise InvariantViolationError("Las monedas de la línea deben coincidir")
        if self.discount.amount > self.subtotal.amount:
            raise InvariantViolationError("El descuento no puede superar el subtotal")

    @property
    def subtotal(self) -> Money:
        with localcontext(Context(prec=40, rounding=ROUND_HALF_EVEN)):
            return self.unit_price.multiply(self.quantity)

    @property
    def total(self) -> Money:
        with localcontext(Context(prec=40, rounding=ROUND_HALF_EVEN)):
            return self.subtotal.subtract(self.discount).add(self.tax)
