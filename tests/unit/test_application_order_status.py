"""Validación y confirmación con dobles transaccionales."""

from dataclasses import replace

import pytest

from tests.unit.test_application_catalog import FakeEventPublisher
from tests.unit.test_application_order_add_line import case as case
from tests.unit.test_application_order_create import run, scoped
from universal_business.application.errors import ApplicationError, IdempotencyConflictError
from universal_business.application.idempotency import IdempotencyKey
from universal_business.application.orders.commands import ConfirmOrder, ValidateOrder
from universal_business.application.orders.status_change import (
    ConfirmOrderHandler,
    ValidateOrderHandler,
)
from universal_business.application.unit_of_work import CommitNotAppliedError
from universal_business.domain.orders.events import OrderStatusChanged
from universal_business.domain.orders.value_objects import OrderStatus
from universal_business.domain.shared.errors import StatusTransitionError
from universal_business.domain.shared.value_objects.ids import BusinessId
from universal_business.domain.shared.value_objects.money import Money


class Policy:
    def __init__(self, approved=True):
        self.approved = approved

    def approve(self, *, order, target):
        return self.approved


def setup(case, *, add=True):
    add_cmd, ledger, tx, store, _, _, add_handler = case
    if add:
        run(add_handler, tx, add_cmd, FakeEventPublisher())
    scope = dict(
        tenant_id=add_cmd.tenant_id,
        business_id=add_cmd.business_id,
        location_id=add_cmd.location_id,
        order_id=add_cmd.order_id,
    )
    validation = ValidateOrder(**scope, idempotency_key=IdempotencyKey(value="order-validate-1"))
    confirmation = ConfirmOrder(**scope, idempotency_key=IdempotencyKey(value="order-confirm-1"))
    policy = Policy()
    validate = ValidateOrderHandler(orders=tx, guard=tx, policy=policy, idempotency=store)
    confirm = ConfirmOrderHandler(orders=tx, guard=tx, policy=policy, idempotency=store)
    return validation, confirmation, ledger, tx, store, policy, validate, confirm


def test_validate_confirm_and_replay(case):
    validation, confirmation, ledger, tx, _, _, validate, confirm = setup(case)
    publisher = FakeEventPublisher()
    validated = run(validate, tx, validation, publisher)
    assert validated.status == OrderStatus.VALIDATED and validated.total == Money(21, "EUR")
    confirmed = run(confirm, tx, confirmation, publisher)
    assert (
        confirmed.status == OrderStatus.CONFIRMED and ledger.order.status == OrderStatus.CONFIRMED
    )
    assert len(publisher.published) == 2
    assert all(isinstance(event, OrderStatusChanged) for event in publisher.published)
    assert run(confirm, tx, confirmation, publisher) == confirmed
    assert len(publisher.published) == 2


def test_empty_and_out_of_sequence_are_rejected(case):
    validation, confirmation, ledger, tx, store, _, validate, confirm = setup(case, add=False)
    for cmd, handler in ((validation, validate), (confirmation, confirm)):
        with pytest.raises(ApplicationError):
            run(handler, tx, cmd, FakeEventPublisher())
        assert store.reserve(cmd.tenant_id, scoped(cmd), "retry")
    assert ledger.order.status == OrderStatus.DRAFT


def test_confirmation_requires_validated_state(case):
    _, confirmation, ledger, tx, _, _, _, confirm = setup(case)
    with pytest.raises(StatusTransitionError):
        run(confirm, tx, confirmation, FakeEventPublisher())
    assert ledger.order.status == OrderStatus.DRAFT


@pytest.mark.parametrize("invalid", ["scope", "policy", "wrong_command"])
def test_reject_without_committing(case, invalid):
    validation, confirmation, ledger, tx, store, policy, validate, _ = setup(case)
    if invalid == "scope":
        ledger.order = replace(ledger.order, business_id=BusinessId.generate())
    if invalid == "policy":
        policy.approved = False
    cmd = confirmation if invalid == "wrong_command" else validation
    original, publisher = ledger.order, FakeEventPublisher()
    with pytest.raises(ApplicationError):
        run(validate, tx, cmd, publisher)
    assert ledger.order is original and not publisher.published
    assert store.reserve(cmd.tenant_id, scoped(cmd), "retry")


@pytest.mark.parametrize(
    "error,released",
    [(CommitNotAppliedError("not applied"), True), (RuntimeError("unknown"), False)],
)
def test_commit_failure(case, error, released):
    validation, _, ledger, tx, store, _, validate, _ = setup(case)
    original, publisher = ledger.order, FakeEventPublisher()
    tx.failure = error
    with pytest.raises(type(error)):
        run(validate, tx, validation, publisher)
    assert ledger.order is original and not publisher.published
    assert store.reserve(validation.tenant_id, scoped(validation), "retry") is released


def test_complete_failure_retains_key_and_publishes(case):
    validation, _, ledger, tx, store, _, validate, _ = setup(case)
    publisher = FakeEventPublisher()

    def fail(*args):
        raise RuntimeError("complete failed")

    store.complete = fail
    with pytest.raises(RuntimeError, match="complete failed"):
        run(validate, tx, validation, publisher)
    assert ledger.order.status == OrderStatus.VALIDATED and len(publisher.published) == 1
    assert not store.reserve(validation.tenant_id, scoped(validation), "retry")


def test_conflicting_payload_with_same_key(case):
    validation, _, _, tx, _, _, validate, _ = setup(case)
    run(validate, tx, validation, FakeEventPublisher())
    with pytest.raises(IdempotencyConflictError):
        run(
            validate,
            tx,
            replace(validation, order_id=type(validation.order_id).generate()),
            FakeEventPublisher(),
        )


def test_concurrent_removal_rechecks_validated_state(case):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from tests.unit.test_application_order_add_line import Transaction
    from universal_business.application.orders.commands import RemoveOrderLine
    from universal_business.application.orders.remove_line import RemoveOrderLineHandler
    from universal_business.domain.shared.errors import InvariantViolationError

    validation, _, ledger, tx, store, _, validate, _ = setup(case)
    entered, attempted, resume = Event(), Event(), Event()
    original_save = tx.save

    def blocked_save(order):
        entered.set()
        if not resume.wait(5):
            raise TimeoutError("removal did not start")
        original_save(order)

    tx.save = blocked_save
    remove_tx = Transaction(ledger)
    original_protect = remove_tx.protect

    def announce(**scope):
        attempted.set()
        original_protect(**scope)

    remove_tx.protect = announce
    remove = RemoveOrderLineHandler(orders=remove_tx, guard=remove_tx, idempotency=store)
    cmd = RemoveOrderLine(
        tenant_id=validation.tenant_id,
        business_id=validation.business_id,
        location_id=validation.location_id,
        order_id=validation.order_id,
        line_id=ledger.order.lines[0].line_id,
        idempotency_key=IdempotencyKey(value="concurrent-remove"),
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run, validate, tx, validation, FakeEventPublisher())
        assert entered.wait(5)
        second = pool.submit(run, remove, remove_tx, cmd, FakeEventPublisher())
        try:
            assert attempted.wait(5)
        finally:
            resume.set()
        first.result(timeout=5)
        with pytest.raises(InvariantViolationError):
            second.result(timeout=5)
    assert ledger.order.status == OrderStatus.VALIDATED and len(ledger.order.lines) == 1


def test_policy_cannot_mutate_staged_order(case):
    validation, _, ledger, tx, _, policy, validate, _ = setup(case)

    def mutate(*, order, target):
        order.remove_line(order.lines[0].line_id)
        return True

    policy.approve = mutate
    result = run(validate, tx, validation, FakeEventPublisher())
    assert result.total == Money(21, "EUR")
    assert len(ledger.order.lines) == 1
