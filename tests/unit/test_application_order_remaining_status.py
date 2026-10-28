"""Ciclo completo con fakes; no demuestra aislamiento durable."""

from dataclasses import replace

import pytest

from tests.unit.test_application_catalog import FakeEventPublisher
from tests.unit.test_application_order_add_line import case as case
from tests.unit.test_application_order_create import run, scoped
from tests.unit.test_application_order_status import Policy, setup
from universal_business.application.errors import ApplicationError
from universal_business.application.idempotency import IdempotencyKey
from universal_business.application.orders.commands import (
    CancelOrder,
    CompleteOrder,
    DispatchOrder,
    MarkOrderReady,
    PrepareOrder,
    ReturnOrderToDraft,
)
from universal_business.application.orders.status_change import (
    CancelOrderHandler,
    CompleteOrderHandler,
    DispatchOrderHandler,
    MarkOrderReadyHandler,
    PrepareOrderHandler,
    ReturnOrderToDraftHandler,
)
from universal_business.application.unit_of_work import CommitNotAppliedError
from universal_business.domain.orders.events import OrderStatusChanged
from universal_business.domain.orders.value_objects import OrderStatus
from universal_business.domain.shared.errors import StatusTransitionError


@pytest.mark.parametrize(
    "command,handler,source,target",
    [
        (ReturnOrderToDraft, ReturnOrderToDraftHandler, OrderStatus.VALIDATED, OrderStatus.DRAFT),
        (CancelOrder, CancelOrderHandler, OrderStatus.DRAFT, OrderStatus.CANCELLED),
        (CancelOrder, CancelOrderHandler, OrderStatus.DELIVERING, OrderStatus.CANCELLED),
        (PrepareOrder, PrepareOrderHandler, OrderStatus.CONFIRMED, OrderStatus.PREPARING),
        (MarkOrderReady, MarkOrderReadyHandler, OrderStatus.PREPARING, OrderStatus.READY),
        (DispatchOrder, DispatchOrderHandler, OrderStatus.READY, OrderStatus.DELIVERING),
        (CompleteOrder, CompleteOrderHandler, OrderStatus.CONFIRMED, OrderStatus.COMPLETED),
        (CompleteOrder, CompleteOrderHandler, OrderStatus.READY, OrderStatus.COMPLETED),
        (CompleteOrder, CompleteOrderHandler, OrderStatus.DELIVERING, OrderStatus.COMPLETED),
    ],
)
def test_transition_and_replay(case, command, handler, source, target):
    validation, _, ledger, tx, store, _, _, _ = setup(case)
    ledger.order = replace(ledger.order, status=source)
    cmd = command(
        tenant_id=validation.tenant_id,
        business_id=validation.business_id,
        location_id=validation.location_id,
        order_id=validation.order_id,
        idempotency_key=IdempotencyKey(value="order-transition-key"),
    )
    operation = handler(orders=tx, guard=tx, policy=Policy(), idempotency=store)
    publisher = FakeEventPublisher()
    result = run(operation, tx, cmd, publisher)
    assert result.status == target and ledger.order.status == target
    assert len(publisher.published) == 1 and isinstance(publisher.published[0], OrderStatusChanged)
    assert publisher.published[0].previous_status == source
    assert run(operation, tx, cmd, publisher) == result
    assert len(publisher.published) == 1


def test_empty_draft_can_be_cancelled(case):
    validation, _, ledger, tx, store, _, _, _ = setup(case, add=False)
    cmd = CancelOrder(
        tenant_id=validation.tenant_id,
        business_id=validation.business_id,
        location_id=validation.location_id,
        order_id=validation.order_id,
        idempotency_key=IdempotencyKey(value="cancel-empty-order"),
    )
    result = run(
        CancelOrderHandler(orders=tx, guard=tx, policy=Policy(), idempotency=store),
        tx,
        cmd,
        FakeEventPublisher(),
    )
    assert result.total is None and ledger.order.status == OrderStatus.CANCELLED


def test_terminal_state_and_policy_rejected(case):
    validation, _, ledger, tx, store, _, _, _ = setup(case)
    cmd = CompleteOrder(
        tenant_id=validation.tenant_id,
        business_id=validation.business_id,
        location_id=validation.location_id,
        order_id=validation.order_id,
        idempotency_key=IdempotencyKey(value="complete-order-key"),
    )
    ledger.order = replace(ledger.order, status=OrderStatus.CANCELLED)
    operation = CompleteOrderHandler(orders=tx, guard=tx, policy=Policy(), idempotency=store)
    with pytest.raises(StatusTransitionError):
        run(operation, tx, cmd, FakeEventPublisher())
    assert ledger.order.status == OrderStatus.CANCELLED
    ledger.order = replace(ledger.order, status=OrderStatus.CONFIRMED)
    rejected = CompleteOrderHandler(orders=tx, guard=tx, policy=Policy(False), idempotency=store)
    with pytest.raises(ApplicationError):
        run(rejected, tx, cmd, FakeEventPublisher())
    assert ledger.order.status == OrderStatus.CONFIRMED


@pytest.mark.parametrize(
    "failure,released",
    [(CommitNotAppliedError("not applied"), True), (RuntimeError("uncertain"), False)],
)
def test_cancel_commit_failure(case, failure, released):
    validation, _, ledger, tx, store, _, _, _ = setup(case, add=False)
    cmd = CancelOrder(
        tenant_id=validation.tenant_id,
        business_id=validation.business_id,
        location_id=validation.location_id,
        order_id=validation.order_id,
        idempotency_key=IdempotencyKey(value="cancel-empty-order"),
    )
    tx.failure = failure
    publisher = FakeEventPublisher()
    with pytest.raises(type(failure)):
        run(
            CancelOrderHandler(orders=tx, guard=tx, policy=Policy(), idempotency=store),
            tx,
            cmd,
            publisher,
        )
    assert ledger.order.status == OrderStatus.DRAFT and not publisher.published
    assert store.reserve(cmd.tenant_id, scoped(cmd), "retry") is released
