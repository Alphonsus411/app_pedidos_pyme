"""Política propuesta de transición de pedidos, sin modificar el agregado."""

from __future__ import annotations

from types import MappingProxyType

from universal_business.domain.orders.value_objects import OrderStatus
from universal_business.domain.shared.errors import StatusTransitionError

_ALLOWED: MappingProxyType[OrderStatus, frozenset[OrderStatus]] = MappingProxyType(
    {
        OrderStatus.DRAFT: frozenset({OrderStatus.VALIDATED, OrderStatus.CANCELLED}),
        OrderStatus.VALIDATED: frozenset(
            {OrderStatus.DRAFT, OrderStatus.CONFIRMED, OrderStatus.CANCELLED}
        ),
        OrderStatus.CONFIRMED: frozenset(
            {OrderStatus.PREPARING, OrderStatus.COMPLETED, OrderStatus.CANCELLED}
        ),
        OrderStatus.PREPARING: frozenset({OrderStatus.READY, OrderStatus.CANCELLED}),
        OrderStatus.READY: frozenset(
            {OrderStatus.DELIVERING, OrderStatus.COMPLETED, OrderStatus.CANCELLED}
        ),
        OrderStatus.DELIVERING: frozenset({OrderStatus.COMPLETED, OrderStatus.CANCELLED}),
        OrderStatus.COMPLETED: frozenset(),
        OrderStatus.CANCELLED: frozenset(),
    }
)


def allowed_order_transitions(source: OrderStatus) -> frozenset[OrderStatus]:
    """Devolver destinos válidos, sin aplicar reglas de autorización ni modificar el pedido."""
    if not isinstance(source, OrderStatus):
        raise StatusTransitionError("El estado de origen debe ser OrderStatus")
    return _ALLOWED[source]


def validate_order_transition(source: OrderStatus, target: OrderStatus) -> None:
    """Validar solo la matriz: confirmar también requiere líneas y totales válidos.

    Repetir un estado no es una transición. La cancelación por sí sola no
    desencadena reembolsos, cambios de stock ni otras acciones externas.
    """
    if not isinstance(target, OrderStatus):
        raise StatusTransitionError("El estado de destino debe ser OrderStatus")
    if target not in allowed_order_transitions(source):
        raise StatusTransitionError(f"Transición de pedido no permitida: {source} -> {target}")
