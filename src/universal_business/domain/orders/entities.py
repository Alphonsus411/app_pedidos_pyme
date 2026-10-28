"""Agregado de pedido con edición controlada de líneas de borrador."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, localcontext
from uuid import UUID

from universal_business.domain.orders.line import OrderLine
from universal_business.domain.orders.value_objects import OrderChannel, OrderStatus
from universal_business.domain.shared.base import BaseEntity
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CustomerId,
    LocationId,
    OrderId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money


@dataclass(kw_only=True)
class Order(BaseEntity[OrderId]):
    """Pedido — genérico (no sectorial)."""

    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId  # OBLIGATORIO: pedido asociado a un establecimiento
    status: OrderStatus
    channel: OrderChannel
    total: Money | None = None
    customer_id: CustomerId | None = None
    external_ref: str | None = None
    notes: str | None = None
    lines: tuple[OrderLine, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.status, OrderStatus):
            raise InvariantViolationError("Order.status debe ser OrderStatus")
        if not isinstance(self.channel, OrderChannel):
            raise InvariantViolationError("Order.channel debe ser OrderChannel")
        if self.total is not None and not isinstance(self.total, Money):
            raise InvariantViolationError("Order.total debe ser Money")
        calculated = _calculate_total(self.lines)
        if self.lines:
            if self.total is not None and self.total != calculated:
                raise InvariantViolationError("El total no coincide con las líneas")
            self.total = calculated
        if self.external_ref is not None:
            er = self.external_ref.strip()
            if not er:
                raise InvariantViolationError("Order.external_ref vacío no permitido")
            object.__setattr__(self, "external_ref", er)

    def add_line(self, line: OrderLine) -> None:
        """Añadir una línea al borrador y recalcular, sin validar el catálogo."""
        if self.status != OrderStatus.DRAFT:
            raise InvariantViolationError("Solo se pueden editar líneas en DRAFT")
        new_lines = (*self.lines, line)
        total = _calculate_total(new_lines)
        self.lines = new_lines
        self.total = total
        self.touch()

    def remove_line(self, line_id: UUID) -> None:
        """Eliminar una línea existente del borrador y recalcular."""
        if self.status != OrderStatus.DRAFT:
            raise InvariantViolationError("Solo se pueden editar líneas en DRAFT")
        if not isinstance(line_id, UUID) or not any(line.line_id == line_id for line in self.lines):
            raise InvariantViolationError("Línea de pedido inexistente")
        new_lines = tuple(line for line in self.lines if line.line_id != line_id)
        total = _calculate_total(new_lines)
        self.lines = new_lines
        self.total = total
        self.touch()


def _calculate_total(lines: tuple[OrderLine, ...]) -> Money | None:
    """Calcular total con moneda única, o None si aún no existen líneas."""
    if not isinstance(lines, tuple):
        raise InvariantViolationError("Order.lines debe ser una tupla")
    if len(lines) > 1000:
        raise InvariantViolationError("Un pedido admite hasta 1000 líneas")
    if not lines:
        return None
    if not all(isinstance(line, OrderLine) for line in lines):
        raise InvariantViolationError("Order.lines debe contener OrderLine")
    if len({line.line_id for line in lines}) != len(lines):
        raise InvariantViolationError("Identificador de línea duplicado")
    currency = lines[0].unit_price.currency
    if any(line.unit_price.currency != currency for line in lines):
        raise InvariantViolationError("Todas las líneas deben compartir moneda")
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        total = Money.zero(currency)
        for line in lines:
            total = total.add(line.total)
        return total


__all__ = ["Order"]
