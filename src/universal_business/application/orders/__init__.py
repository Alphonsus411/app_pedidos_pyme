"""Casos de uso de pedidos."""

from universal_business.application.orders.add_line import (
    AddOrderLineHandler,
    OrderLinePolicy,
    OrderLineResult,
)
from universal_business.application.orders.commands import (
    AddOrderLine,
    ConfirmOrder,
    CreateOrder,
    RemoveOrderLine,
    ValidateOrder,
)
from universal_business.application.orders.creation import CreateOrderHandler, OrderDraftCreated
from universal_business.application.orders.remove_line import (
    OrderLineRemoval,
    RemoveOrderLineHandler,
)
from universal_business.application.orders.status_change import (
    ConfirmOrderHandler,
    OrderStatusResult,
    OrderTransitionPolicy,
    ValidateOrderHandler,
)

__all__ = [
    "CreateOrder",
    "CreateOrderHandler",
    "OrderDraftCreated",
    "AddOrderLine",
    "AddOrderLineHandler",
    "OrderLinePolicy",
    "OrderLineResult",
    "RemoveOrderLine",
    "RemoveOrderLineHandler",
    "OrderLineRemoval",
    "ValidateOrder",
    "ValidateOrderHandler",
    "ConfirmOrder",
    "ConfirmOrderHandler",
    "OrderStatusResult",
    "OrderTransitionPolicy",
]
