"""Retirada de línea con fakes transaccionales."""

from dataclasses import replace
from uuid import uuid4

import pytest

from tests.unit.test_application_catalog import FakeEventPublisher
from tests.unit.test_application_order_add_line import case as case
from tests.unit.test_application_order_create import run, scoped
from universal_business.application.errors import ApplicationError, IdempotencyConflictError
from universal_business.application.idempotency import IdempotencyKey
from universal_business.application.orders.commands import RemoveOrderLine
from universal_business.application.orders.remove_line import RemoveOrderLineHandler
from universal_business.application.unit_of_work import CommitNotAppliedError
from universal_business.domain.orders.events import OrderLineRemoved
from universal_business.domain.orders.value_objects import OrderStatus
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import BusinessId


def prepare(case):
    add_cmd, ledger, tx, store, _, _, add_handler = case
    run(add_handler, tx, add_cmd, FakeEventPublisher())
    cmd = RemoveOrderLine(
        tenant_id=add_cmd.tenant_id,
        business_id=add_cmd.business_id,
        location_id=add_cmd.location_id,
        order_id=add_cmd.order_id,
        line_id=add_cmd.line_id,
        idempotency_key=IdempotencyKey(value="remove-line-001"),
    )
    return cmd, ledger, tx, store, RemoveOrderLineHandler(orders=tx, guard=tx, idempotency=store)


def test_remove_last_line_and_replay(case):
    cmd, ledger, tx, _, handler = prepare(case)
    publisher = FakeEventPublisher()
    result = run(handler, tx, cmd, publisher)
    assert result.total is None and ledger.order.total is None and not ledger.order.lines
    assert len(publisher.published) == 1 and isinstance(publisher.published[0], OrderLineRemoved)
    assert publisher.published[0].line_id == cmd.line_id
    assert run(handler, tx, cmd, publisher) == result
    assert len(publisher.published) == 1
    with pytest.raises(IdempotencyConflictError):
        run(handler, tx, replace(cmd, line_id=uuid4()), publisher)


@pytest.mark.parametrize("invalid", ["scope", "state", "missing"])
def test_rejected_removal_releases_key(case, invalid):
    cmd, ledger, tx, store, handler = prepare(case)
    if invalid == "scope":
        ledger.order = replace(ledger.order, business_id=BusinessId.generate())
    if invalid == "state":
        ledger.order = replace(ledger.order, status=OrderStatus.CONFIRMED)
    if invalid == "missing":
        cmd = replace(cmd, line_id=uuid4())
    original = ledger.order
    publisher = FakeEventPublisher()
    with pytest.raises((ApplicationError, InvariantViolationError)):
        run(handler, tx, cmd, publisher)
    assert ledger.order is original and not publisher.published
    assert store.reserve(cmd.tenant_id, scoped(cmd), "retry")


@pytest.mark.parametrize(
    "error,released",
    [(CommitNotAppliedError("not applied"), True), (RuntimeError("unknown"), False)],
)
def test_failed_commit_preserves_original(case, error, released):
    cmd, ledger, tx, store, handler = prepare(case)
    original, publisher = ledger.order, FakeEventPublisher()
    tx.failure = error
    with pytest.raises(type(error)):
        run(handler, tx, cmd, publisher)
    assert ledger.order is original and len(original.lines) == 1 and not publisher.published
    assert store.reserve(cmd.tenant_id, scoped(cmd), "retry") is released


def test_complete_failure_after_commit_keeps_key(case):
    cmd, ledger, tx, store, handler = prepare(case)
    publisher = FakeEventPublisher()

    def fail(*args):
        raise RuntimeError("complete failed")

    store.complete = fail
    with pytest.raises(RuntimeError, match="complete failed"):
        run(handler, tx, cmd, publisher)
    assert not ledger.order.lines and len(publisher.published) == 1
    assert not store.reserve(cmd.tenant_id, scoped(cmd), "retry")
