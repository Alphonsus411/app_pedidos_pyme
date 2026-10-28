from dataclasses import FrozenInstanceError, replace

import pytest

from tests.unit.test_application_catalog import FakeEventPublisher
from tests.unit.test_application_order_add_line import case as case
from tests.unit.test_application_order_create import run
from universal_business.application.errors import ApplicationError
from universal_business.application.orders.queries import GetOrder
from universal_business.application.orders.query_handlers import GetOrderHandler
from universal_business.domain.orders.value_objects import OrderStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    OrderId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money


class Repo:
    def __init__(self, order):
        self.order = order
        self.calls = []

    def get(self, *, tenant_id, order_id):
        self.calls.append((tenant_id, order_id))
        return self.order


def setup(case):
    cmd, ledger, tx, _, _, _, handler = case
    run(handler, tx, cmd, FakeEventPublisher())
    query = GetOrder(
        tenant_id=cmd.tenant_id,
        business_id=cmd.business_id,
        location_id=cmd.location_id,
        order_id=cmd.order_id,
    )
    return query, ledger.order


def test_result_is_immutable_snapshot(case):
    query, order = setup(case)
    repo = Repo(order)
    view = GetOrderHandler(orders=repo).handle(query)
    assert view is not None and view.total == Money(21, "EUR")
    assert len(view.lines) == 1 and view.lines[0].name == "Servicio"
    assert repo.calls == [(query.tenant_id, query.order_id)]
    with pytest.raises(FrozenInstanceError):
        view.status = OrderStatus.CANCELLED
    order.remove_line(order.lines[0].line_id)
    assert len(view.lines) == 1 and view.total == Money(21, "EUR")


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", TenantId.generate()),
        ("business_id", BusinessId.generate()),
        ("location_id", LocationId.generate()),
        ("id", OrderId.generate()),
    ],
)
def test_cross_scope_and_incorrect_id_are_not_returned(case, field, value):
    query, order = setup(case)
    assert GetOrderHandler(orders=Repo(replace(order, **{field: value}))).handle(query) is None


def test_missing_and_invalid_query(case):
    query, _ = setup(case)
    repo = Repo(None)
    assert GetOrderHandler(orders=repo).handle(query) is None
    with pytest.raises(ApplicationError):
        GetOrderHandler(orders=repo).handle(replace(query, business_id=None))
    assert len(repo.calls) == 1


def test_legacy_order_without_lines(case):
    query, order = setup(case)
    legacy = replace(order, lines=(), total=Money(5, "EUR"))
    view = GetOrderHandler(orders=Repo(legacy)).handle(query)
    assert view is not None and view.lines == () and view.total == Money(5, "EUR")
