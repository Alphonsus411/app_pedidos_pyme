"""Behavioral regression matrix for all idempotent create handlers."""

from dataclasses import replace

import pytest

from tests.unit.test_application_catalog import (
    FakeCatalogCategoryRepository,
    FakeEventPublisher,
    FakeIdempotencyStore,
    FakeOfferingRepository,
    FakeUnitOfWork,
)
from tests.unit.test_application_resources import (
    FakeResourceRepository,
    FakeResourceTypeRepository,
    _seed_resource_type,
)
from universal_business.application.catalog.commands import CreateCatalogCategory, CreateOffering
from universal_business.application.catalog.handlers import (
    CreateCatalogCategoryHandler,
    CreateOfferingHandler,
)
from universal_business.application.errors import ApplicationError
from universal_business.application.events.dispatcher import DomainEventDispatcher
from universal_business.application.execution import execute_use_case
from universal_business.application.idempotency import IdempotencyKey, scoped_idempotency_key
from universal_business.application.resources.commands import CreateResource, CreateResourceType
from universal_business.application.resources.handlers import (
    CreateResourceHandler,
    CreateResourceTypeHandler,
)
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CatalogCategoryId,
    OfferingId,
    ResourceId,
    ResourceTypeId,
    TenantId,
)


def make_case(kind):
    tenant, business = TenantId.generate(), BusinessId.generate()
    key = IdempotencyKey(value="matrix-key-001")
    store = FakeIdempotencyStore()
    if kind == "offering":
        repo = FakeOfferingRepository()
        handler = CreateOfferingHandler(offering_repository=repo, idempotency_store=store)
        command = CreateOffering(
            tenant_id=tenant,
            business_id=business,
            offering_id=OfferingId.generate(),
            name="A",
            idempotency_key=key,
        )
    elif kind == "category":
        repo = FakeCatalogCategoryRepository()
        handler = CreateCatalogCategoryHandler(category_repository=repo, idempotency_store=store)
        command = CreateCatalogCategory(
            tenant_id=tenant,
            business_id=business,
            category_id=CatalogCategoryId.generate(),
            name="A",
            idempotency_key=key,
        )
    elif kind == "resource_type":
        repo = FakeResourceTypeRepository()
        handler = CreateResourceTypeHandler(resource_type_repo=repo, idempotency_store=store)
        command = CreateResourceType(
            tenant_id=tenant,
            business_id=business,
            resource_type_id=ResourceTypeId.generate(),
            name="A",
            idempotency_key=key,
        )
    else:
        repo = FakeResourceRepository()
        types = FakeResourceTypeRepository()
        type_id = ResourceTypeId.generate()
        _seed_resource_type(types, tenant_id=tenant, business_id=business, resource_type_id=type_id)
        handler = CreateResourceHandler(
            resource_repo=repo, resource_type_repo=types, idempotency_store=store
        )
        command = CreateResource(
            tenant_id=tenant,
            business_id=business,
            resource_id=ResourceId.generate(),
            resource_type_id=type_id,
            name="A",
            idempotency_key=key,
        )
    return handler, command, store


def run(handler, command, uow=None):
    return execute_use_case(
        handler=handler,
        input=command,
        unit_of_work=uow or FakeUnitOfWork(),
        event_dispatcher=DomainEventDispatcher(),
        event_publisher=FakeEventPublisher(),
    )


@pytest.mark.parametrize("kind", ["offering", "category", "resource_type", "resource"])
def test_replay_conflict_and_new_key_same_identifier(kind):
    handler, command, store = make_case(kind)
    first = run(handler, command)
    assert run(handler, command) is first
    with pytest.raises(ApplicationError):
        run(handler, replace(command, name="Different"))
    with pytest.raises(ApplicationError, match="already exists"):
        run(
            handler,
            replace(
                command, name="Different", idempotency_key=IdempotencyKey(value="new-key-00001")
            ),
        )
    assert run(handler, command) is first


@pytest.mark.parametrize("kind", ["offering", "category", "resource_type", "resource"])
def test_failed_commit_releases_owned_key(kind):
    handler, command, store = make_case(kind)
    uow = FakeUnitOfWork()
    uow.fail_on_commit = True
    with pytest.raises(RuntimeError, match="commit failure"):
        run(handler, command, uow)
    scoped = scoped_idempotency_key(
        business_id=command.business_id,
        operation=f"{type(command).__module__}.{type(command).__qualname__}",
        key=command.idempotency_key,
    )
    assert store.reserve(command.tenant_id, scoped, "can-retry")


@pytest.mark.parametrize("kind", ["offering", "category", "resource_type", "resource"])
def test_complete_failure_after_commit_preserves_reservation(kind):
    handler, command, store = make_case(kind)
    releases = []
    original_release = store.release

    def release(tenant_id, key):
        releases.append(key)
        original_release(tenant_id, key)

    def fail_complete(*args):
        raise RuntimeError("idempotency storage unavailable")

    store.release = release
    store.complete = fail_complete
    publisher = FakeEventPublisher()
    uow = FakeUnitOfWork()
    with pytest.raises(RuntimeError, match="idempotency storage unavailable"):
        execute_use_case(
            handler=handler,
            input=command,
            unit_of_work=uow,
            event_dispatcher=DomainEventDispatcher(),
            event_publisher=publisher,
        )
    scoped = scoped_idempotency_key(
        business_id=command.business_id,
        operation=f"{type(command).__module__}.{type(command).__qualname__}",
        key=command.idempotency_key,
    )
    assert uow.commit_count == 1
    assert uow.rollback_count == 0
    assert releases == []
    assert not store.reserve(command.tenant_id, scoped, "retry")
    assert publisher.published
    with pytest.raises(ApplicationError):
        run(handler, command)


@pytest.mark.parametrize("kind", ["offering", "category", "resource_type", "resource"])
def test_concurrent_same_key_rejects_second_request(kind):
    """Concurrencia entre handlers usando un store fake de reserva atómica."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock

    handler, command, store = make_case(kind)
    repo = {
        "offering": lambda: handler._offering_repository,
        "category": lambda: handler._category_repository,
        "resource_type": lambda: handler.resource_type_repo,
        "resource": lambda: handler.resource_repo,
    }[kind]()
    entered, resume, lock = Event(), Event(), Lock()
    original_save, original_reserve = repo.save, store.reserve

    def blocking_save(entity):
        entered.set()
        if not resume.wait(timeout=5):
            raise RuntimeError("test synchronization timed out")
        original_save(entity)

    def atomic_reserve(tenant_id, key, digest):
        with lock:
            return original_reserve(tenant_id, key, digest)

    repo.save = blocking_save
    store.reserve = atomic_reserve
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run, handler, command)
        try:
            assert entered.wait(timeout=5)
            second = pool.submit(run, handler, command)
            with pytest.raises(ApplicationError):
                second.result(timeout=5)
        finally:
            resume.set()
        first_result = first.result(timeout=5)
    assert run(handler, command) is first_result


@pytest.mark.parametrize("kind", ["offering", "category", "resource_type", "resource"])
def test_repository_failure_releases_reservation_and_publishes_nothing(kind):
    handler, command, store = make_case(kind)
    repo = {
        "offering": lambda: handler._offering_repository,
        "category": lambda: handler._category_repository,
        "resource_type": lambda: handler.resource_type_repo,
        "resource": lambda: handler.resource_repo,
    }[kind]()

    def fail_save(entity):
        raise RuntimeError("repository unavailable")

    repo.save = fail_save
    publisher, uow = FakeEventPublisher(), FakeUnitOfWork()
    with pytest.raises(RuntimeError, match="repository unavailable"):
        execute_use_case(
            handler=handler,
            input=command,
            unit_of_work=uow,
            event_dispatcher=DomainEventDispatcher(),
            event_publisher=publisher,
        )
    scoped = scoped_idempotency_key(
        business_id=command.business_id,
        operation=f"{type(command).__module__}.{type(command).__qualname__}",
        key=command.idempotency_key,
    )
    assert uow.commit_count == 0
    assert publisher.published == []
    assert store.reserve(command.tenant_id, scoped, "retry")


@pytest.mark.parametrize("kind", ["offering", "category", "resource_type", "resource"])
@pytest.mark.parametrize("field", ["tenant_id", "business_id", "id"])
def test_corrupt_cached_result_is_not_returned(kind, field):
    """Un store defectuoso no debe hacer que el replay devuelva otro agregado o ámbito."""
    handler, command, _ = make_case(kind)
    original = run(handler, command)
    wrong = type(getattr(original, field)).generate()
    object.__setattr__(original, field, wrong)
    with pytest.raises(ApplicationError):
        run(handler, command)


@pytest.mark.parametrize("kind", ["offering", "category", "resource_type", "resource"])
def test_unknown_commit_outcome_keeps_key_reserved(kind):
    """Una desconexión durante commit no implica que la escritura no se haya aplicado."""
    handler, command, store = make_case(kind)

    class AmbiguousUnitOfWork(FakeUnitOfWork):
        def commit(self):
            self.commit_count += 1  # Simula que pudo aplicarse antes de perder la respuesta.
            raise RuntimeError("commit outcome unknown")

    publisher = FakeEventPublisher()
    with pytest.raises(RuntimeError, match="commit outcome unknown"):
        execute_use_case(
            handler=handler,
            input=command,
            unit_of_work=AmbiguousUnitOfWork(),
            event_dispatcher=DomainEventDispatcher(),
            event_publisher=publisher,
        )
    scoped = scoped_idempotency_key(
        business_id=command.business_id,
        operation=f"{type(command).__module__}.{type(command).__qualname__}",
        key=command.idempotency_key,
    )
    assert not store.reserve(command.tenant_id, scoped, "retry")
    assert publisher.published == []
    with pytest.raises(ApplicationError):
        run(handler, command)


@pytest.mark.parametrize("kind", ["offering", "category", "resource_type", "resource"])
def test_context_exit_failure_after_commit_keeps_key_reserved(kind):
    handler, command, store = make_case(kind)

    class FailedExitUnitOfWork(FakeUnitOfWork):
        def __exit__(self, exc_type, exc, tb):
            super().__exit__(exc_type, exc, tb)
            raise RuntimeError("exit failed after commit")

    with pytest.raises(RuntimeError, match="exit failed after commit"):
        run(handler, command, FailedExitUnitOfWork())
    scoped = scoped_idempotency_key(
        business_id=command.business_id,
        operation=f"{type(command).__module__}.{type(command).__qualname__}",
        key=command.idempotency_key,
    )
    assert not store.reserve(command.tenant_id, scoped, "retry")


@pytest.mark.parametrize("kind", ["offering", "category", "resource_type", "resource"])
@pytest.mark.parametrize("failure", ["dispatcher", "publisher"])
def test_complete_and_event_failure_preserve_both_errors(kind, failure):
    handler, command, store = make_case(kind)

    def fail_complete(*args):
        raise RuntimeError("complete failed")

    store.complete = fail_complete
    dispatcher, publisher, uow = DomainEventDispatcher(), FakeEventPublisher(), FakeUnitOfWork()
    if failure == "dispatcher":

        def fail_dispatch(events):
            raise ValueError("dispatch failed")

        dispatcher.dispatch_many = fail_dispatch
    else:

        def fail_publish(events):
            raise ValueError("publish failed")

        publisher.publish_many = fail_publish

    with pytest.raises(RuntimeError, match="complete failed") as caught:
        execute_use_case(
            handler=handler,
            input=command,
            unit_of_work=uow,
            event_dispatcher=dispatcher,
            event_publisher=publisher,
        )
    assert isinstance(caught.value.__cause__, ValueError)
    assert str(caught.value.__cause__) == (
        "dispatch failed" if failure == "dispatcher" else "publish failed"
    )
    assert uow.commit_count == 1
    scoped = scoped_idempotency_key(
        business_id=command.business_id,
        operation=f"{type(command).__module__}.{type(command).__qualname__}",
        key=command.idempotency_key,
    )
    assert not store.reserve(command.tenant_id, scoped, "retry")
    if failure == "dispatcher":
        assert publisher.published == []
