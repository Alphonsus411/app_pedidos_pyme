"""Flujo integrado con dobles de puertos; no prueba una base real."""

from dataclasses import replace
from threading import Lock

from tests.unit.test_application_catalog import FakeEventPublisher
from tests.unit.test_application_order_add_line import Policy as LinePolicy
from tests.unit.test_application_order_add_line import case as case
from tests.unit.test_application_order_create import run
from tests.unit.test_application_order_status import Policy as TransitionPolicy
from tests.unit.test_application_reservation_create import FixedRepo
from universal_business.application.idempotency import IdempotencyKey
from universal_business.application.orders.add_line import AddOrderLineHandler
from universal_business.application.orders.commands import ConfirmOrder, CreateOrder, ValidateOrder
from universal_business.application.orders.creation import CreateOrderHandler
from universal_business.application.orders.queries import GetOrder, ListOrdersByLocation
from universal_business.application.orders.query_handlers import (
    GetOrderHandler,
    ListOrdersByLocationHandler,
)
from universal_business.application.orders.status_change import (
    ConfirmOrderHandler,
    ValidateOrderHandler,
)
from universal_business.domain.business.entities import Location
from universal_business.domain.business.value_objects import Address, LocationStatus, OperatingHours
from universal_business.domain.orders.events import OrderCreated, OrderLineAdded, OrderStatusChanged
from universal_business.domain.orders.value_objects import OrderChannel, OrderStatus
from universal_business.domain.shared.value_objects.money import Money


class Ledger:
    def __init__(self):
        self.order, self.lock = None, Lock()


class Session:
    """Cada ejecución almacena una copia hasta un commit simulado."""

    def __init__(self, ledger):
        self.ledger, self.pending, self.held = ledger, None, False

    def __enter__(self):
        return self

    def protect(self, **scope):
        self.ledger.lock.acquire()
        self.held = True

    def get(self, *, tenant_id, order_id):
        order = self.ledger.order
        return order if order and order.tenant_id == tenant_id and order.id == order_id else None

    def list_by_location(self, *, tenant_id, location_id, status, limit):
        order = self.ledger.order
        if order and order.tenant_id == tenant_id and order.location_id == location_id:
            if status is None or order.status == status:
                return [order][:limit]
        return []

    def save(self, order):
        self.pending = order

    def commit(self):
        if self.pending is not None:
            self.ledger.order = self.pending

    def __exit__(self, exc_type, exc, tb):
        self.pending = None
        if self.held:
            self.held = False
            self.ledger.lock.release()


def test_order_flow_and_retries(case):
    line_command, _, _, store, offerings, _, _ = case
    tid, bid, lid, oid = (
        line_command.tenant_id,
        line_command.business_id,
        line_command.location_id,
        line_command.order_id,
    )
    location = Location(
        id=lid,
        tenant_id=tid,
        business_id=bid,
        name="Tienda",
        address=Address(country_code="ES"),
        timezone="Europe/Madrid",
        operating_hours=OperatingHours(),
        status=LocationStatus.OPEN,
    )
    ledger, publisher = Ledger(), FakeEventPublisher()
    same_key = IdempotencyKey(value="shared-operation-key")
    create_cmd = CreateOrder(
        tenant_id=tid,
        business_id=bid,
        location_id=lid,
        order_id=oid,
        channel=OrderChannel.WEB,
        idempotency_key=same_key,
    )
    create_tx = Session(ledger)
    create = CreateOrderHandler(
        orders=create_tx,
        locations=FixedRepo(location),
        customers=FixedRepo(None),
        idempotency=store,
    )
    initial = run(create, create_tx, create_cmd, publisher)
    add_cmd = replace(line_command, idempotency_key=same_key)
    add_tx = Session(ledger)
    add = AddOrderLineHandler(
        orders=add_tx, offerings=offerings, guard=add_tx, policy=LinePolicy(), idempotency=store
    )
    run(add, add_tx, add_cmd, publisher)
    scope = dict(
        tenant_id=tid, business_id=bid, location_id=lid, order_id=oid, idempotency_key=same_key
    )
    validation, confirmation = ValidateOrder(**scope), ConfirmOrder(**scope)
    validate_tx, confirm_tx = Session(ledger), Session(ledger)
    validate = ValidateOrderHandler(
        orders=validate_tx, guard=validate_tx, policy=TransitionPolicy(), idempotency=store
    )
    confirm = ConfirmOrderHandler(
        orders=confirm_tx, guard=confirm_tx, policy=TransitionPolicy(), idempotency=store
    )
    run(validate, validate_tx, validation, publisher)
    confirmed = run(confirm, confirm_tx, confirmation, publisher)
    assert confirmed.total == Money(21, "EUR")
    # El replay de la creación no sustituye el pedido ya confirmado.
    assert run(create, create_tx, create_cmd, publisher) == initial
    assert run(confirm, confirm_tx, confirmation, publisher) == confirmed
    assert [type(event) for event in publisher.published] == [
        OrderCreated,
        OrderLineAdded,
        OrderStatusChanged,
        OrderStatusChanged,
    ]
    query_repo = Session(ledger)
    view = GetOrderHandler(orders=query_repo).handle(
        GetOrder(tenant_id=tid, business_id=bid, location_id=lid, order_id=oid)
    )
    assert view is not None and view.status == OrderStatus.CONFIRMED
    assert len(view.lines) == 1 and view.total == Money(21, "EUR")
    listed = ListOrdersByLocationHandler(orders=query_repo).handle(
        ListOrdersByLocation(
            tenant_id=tid, business_id=bid, location_id=lid, status=OrderStatus.CONFIRMED
        )
    )
    assert listed == (view,)
