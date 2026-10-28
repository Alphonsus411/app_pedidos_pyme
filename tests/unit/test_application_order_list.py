from dataclasses import replace

import pytest

from tests.unit.test_application_order_add_line import case as case
from tests.unit.test_application_order_query import setup
from universal_business.application.errors import ApplicationError
from universal_business.application.orders.queries import ListOrdersByLocation
from universal_business.application.orders.query_handlers import ListOrdersByLocationHandler
from universal_business.domain.orders.value_objects import OrderStatus
from universal_business.domain.shared.value_objects.ids import BusinessId, LocationId, TenantId


class Repo:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def list_by_location(self, **kwargs):
        self.calls.append(kwargs)
        return self.rows


def test_list_returns_immutable_views_and_passes_filters(case):
    get, order = setup(case)
    repo = Repo([order])
    query = ListOrdersByLocation(
        tenant_id=get.tenant_id,
        business_id=get.business_id,
        location_id=get.location_id,
        status=OrderStatus.DRAFT,
        limit=7,
    )
    result = ListOrdersByLocationHandler(orders=repo).handle(query)
    assert isinstance(result, tuple) and len(result) == 1 and result[0].order_id == order.id
    assert repo.calls == [
        dict(
            tenant_id=get.tenant_id, location_id=get.location_id, status=OrderStatus.DRAFT, limit=7
        )
    ]
    order.remove_line(order.lines[0].line_id)
    assert len(result[0].lines) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", TenantId.generate()),
        ("business_id", BusinessId.generate()),
        ("location_id", LocationId.generate()),
        ("status", OrderStatus.CONFIRMED),
    ],
)
def test_repo_bad_scope_or_filter_fails_entire_result(case, field, value):
    get, order = setup(case)
    repo = Repo([order, replace(order, **{field: value})])
    query = ListOrdersByLocation(
        tenant_id=get.tenant_id,
        business_id=get.business_id,
        location_id=get.location_id,
        status=OrderStatus.DRAFT,
    )
    with pytest.raises(ApplicationError):
        ListOrdersByLocationHandler(orders=repo).handle(query)


@pytest.mark.parametrize(
    "field,value",
    [
        ("limit", 0),
        ("limit", 101),
        ("limit", True),
        ("limit", 1.5),
        ("status", "draft"),
        ("business_id", None),
    ],
)
def test_invalid_query_does_not_call_repository(case, field, value):
    get, order = setup(case)
    query = ListOrdersByLocation(
        tenant_id=get.tenant_id, business_id=get.business_id, location_id=get.location_id
    )
    repo = Repo([order])
    with pytest.raises(ApplicationError):
        ListOrdersByLocationHandler(orders=repo).handle(replace(query, **{field: value}))
    assert not repo.calls


def test_rejects_over_limit_and_duplicates(case):
    get, order = setup(case)
    query = ListOrdersByLocation(
        tenant_id=get.tenant_id, business_id=get.business_id, location_id=get.location_id, limit=1
    )
    with pytest.raises(ApplicationError):
        ListOrdersByLocationHandler(orders=Repo([order, order])).handle(query)
    with pytest.raises(ApplicationError):
        ListOrdersByLocationHandler(orders=Repo([order, order])).handle(replace(query, limit=2))


def test_empty_result(case):
    get, _ = setup(case)
    query = ListOrdersByLocation(
        tenant_id=get.tenant_id, business_id=get.business_id, location_id=get.location_id
    )
    assert ListOrdersByLocationHandler(orders=Repo([])).handle(query) == ()
