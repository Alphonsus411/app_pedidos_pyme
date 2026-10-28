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
