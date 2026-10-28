"""Casos de uso de pedidos."""

from universal_business.application.orders.add_line import (
    AddOrderLineHandler,
    OrderLinePolicy,
    OrderLineResult,
)
from universal_business.application.orders.commands import (
    AddOrderLine,
    CancelOrder,
    CompleteOrder,
    ConfirmOrder,
    CreateOrder,
    DispatchOrder,
    MarkOrderReady,
    PrepareOrder,
    RemoveOrderLine,
    ReturnOrderToDraft,
    ValidateOrder,
)
from universal_business.application.orders.creation import CreateOrderHandler, OrderDraftCreated
from universal_business.application.orders.queries import GetOrder
from universal_business.application.orders.query_handlers import GetOrderHandler, OrderView
from universal_business.application.orders.remove_line import (
    OrderLineRemoval,
    RemoveOrderLineHandler,
)
from universal_business.application.orders.status_change import (
    CancelOrderHandler,
    CompleteOrderHandler,
    ConfirmOrderHandler,
    DispatchOrderHandler,
    MarkOrderReadyHandler,
    OrderStatusResult,
    OrderTransitionPolicy,
    PrepareOrderHandler,
    ReturnOrderToDraftHandler,
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
    "GetOrder",
    "GetOrderHandler",
    "OrderView",
    "ReturnOrderToDraft",
    "ReturnOrderToDraftHandler",
    "CancelOrder",
    "CancelOrderHandler",
    "PrepareOrder",
    "PrepareOrderHandler",
    "MarkOrderReady",
    "MarkOrderReadyHandler",
    "DispatchOrder",
    "DispatchOrderHandler",
    "CompleteOrder",
    "CompleteOrderHandler",
]
