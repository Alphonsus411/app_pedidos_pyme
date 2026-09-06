"""Tests unitarios — Application layer: Resources module (Gate 0.3).

Cubre handlers de command + query, idempotencia, cross-tenant guards,
UnitOfWork semantics y filtros de listado.
"""

from __future__ import annotations

from typing import Any

import pytest

from universal_business.application import (
    ApplicationError,
    DomainEventDispatcher,
    EventPublisher,
    execute_use_case,
)
from universal_business.application.idempotency import (
    IdempotencyKey,
)
from universal_business.application.resources.commands import (
    ActivateResource,
    ArchiveResource,
    AssignResourceToLocation,
    CreateResource,
    CreateResourceType,
)
from universal_business.application.resources.handlers import (
    ActivateResourceHandler,
    ArchiveResourceHandler,
    AssignResourceToLocationHandler,
    CreateResourceHandler,
    CreateResourceTypeHandler,
    GetResourceHandler,
    ListActiveResourcesHandler,
)
from universal_business.application.resources.queries import (
    GetResource,
    ListActiveResources,
)
from universal_business.domain.catalog.value_objects import CatalogItemStatus
from universal_business.domain.resources.entities import (
    Resource,
)
from universal_business.domain.resources.entities import (
    ResourceType as ResourceTypeEntity,
)
from universal_business.domain.resources.events import (
    ResourceActivated,
    ResourceAssignedToLocation,
    ResourceCreated,
    ResourceTypeCreated,
)
from universal_business.domain.resources.value_objects import ResourceStatus
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    ResourceId,
    ResourceTypeId,
    TenantId,
)

# ============================================================================
# Fakes (repositorios, UoW, IdempotencyStore)
# ============================================================================


class FakeResourceTypeRepository:
    """Implementación en memoria de IResourceTypeRepository.

    Key de almacenamiento: solo ``str(resource_type_id.raw)``. Esto permite
    cargar entidades independientemente de su tenant para que el handler
    pueda ejecutar el cross-tenant check comparando ``entity.tenant_id``.
    """

    def __init__(self) -> None:
        self._store: dict[str, ResourceTypeEntity] = {}
        self.save_count = 0

    @staticmethod
    def _k(resource_type_id: ResourceTypeId) -> str:
        return str(resource_type_id.raw)

    def get(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        resource_type_id: ResourceTypeId,
    ) -> ResourceTypeEntity | None:
        entry = self._store.get(self._k(resource_type_id))
        if entry is None:
            return None
        if entry.business_id != business_id:
            return None
        return entry

    def save(self, resource_type: ResourceTypeEntity, /) -> None:
        self._store[self._k(resource_type.id)] = resource_type
        self.save_count += 1

    def list_by_business(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        status: CatalogItemStatus | None = None,
    ) -> list[ResourceTypeEntity]:
        out: list[ResourceTypeEntity] = []
        for rt in self._store.values():
            if rt.tenant_id != tenant_id:
                continue
            if rt.business_id != business_id:
                continue
            if status is not None and rt.status != status:
                continue
            out.append(rt)
        return out


class FakeResourceRepository:
    """Implementación en memoria de IResourceRepository.

    Key de almacenamiento: solo ``str(resource_id.raw)``. Permite cargar
    entidades sin importar tenant para que el handler haga cross-tenant check.
    """

    def __init__(self) -> None:
        self._store: dict[str, Resource] = {}
        self.save_count = 0

    @staticmethod
    def _k(resource_id: ResourceId) -> str:
        return str(resource_id.raw)

    def get(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        resource_id: ResourceId,
    ) -> Resource | None:
        entry = self._store.get(self._k(resource_id))
        if entry is None:
            return None
        if entry.business_id != business_id:
            return None
        return entry

    def save(self, resource: Resource, /) -> None:
        self._store[self._k(resource.id)] = resource
        self.save_count += 1

    def list_by_location(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId,
        status: ResourceStatus | None = None,
        resource_type: Any = None,
        resource_type_id: ResourceTypeId | None = None,
    ) -> list[Resource]:
        out: list[Resource] = []
        for r in self._store.values():
            if r.tenant_id != tenant_id:
                continue
            if r.business_id != business_id:
                continue
            if r.location_id != location_id:
                continue
            if status is not None and r.status != status:
                continue
            if resource_type_id is not None and r.resource_type_id != resource_type_id:
                continue
            out.append(r)
        return out

    def list_by_business(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId | None = None,
        status: ResourceStatus | None = None,
        resource_type_id: ResourceTypeId | None = None,
    ) -> list[Resource]:
        out: list[Resource] = []
        for r in self._store.values():
            if r.tenant_id != tenant_id:
                continue
            if r.business_id != business_id:
                continue
            if location_id is not None and r.location_id != location_id:
                continue
            if status is not None and r.status != status:
                continue
            if resource_type_id is not None and r.resource_type_id != resource_type_id:
                continue
            out.append(r)
        return out

    def list_active(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId | None = None,
        resource_type_id: ResourceTypeId | None = None,
    ) -> list[Resource]:
        out: list[Resource] = []
        for r in self._store.values():
            if r.tenant_id != tenant_id:
                continue
            if r.business_id != business_id:
                continue
            if r.status != ResourceStatus.ACTIVE:
                continue
            if location_id is not None and r.location_id != location_id:
                continue
            if resource_type_id is not None and r.resource_type_id != resource_type_id:
                continue
            out.append(r)
        return out


class FakeUnitOfWork:
    """Fake UnitOfWork context manager (igual semántica que el de test_uow)."""

    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0
        self.entered = False
        self.exited = False
        self._committed = False
        self._rolledback = False

    def __enter__(self) -> FakeUnitOfWork:
        self.entered = True
        self._committed = False
        self._rolledback = False
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.exited = True
        if exc is not None or not self._committed:
            self.rollback()

    def commit(self) -> None:
        if self._rolledback:
            return
        self._committed = True
        self.commit_count += 1

    def rollback(self) -> None:
        if self._rolledback:
            return
        self._rolledback = True
        self.rollback_count += 1


class FakeIdempotencyStore:
    """Fake IdempotencyStore en memoria con positional-only params."""

    FREE = "FREE"
    RESERVED = "RESERVED"
    DONE = "DONE"

    def __init__(self) -> None:
        self._data: dict[tuple[TenantId, IdempotencyKey], tuple[str, str, object]] = {}
        self.release_calls: list[tuple[TenantId, IdempotencyKey]] = []

    def _k(self, tenant_id: TenantId, key: IdempotencyKey) -> tuple[TenantId, IdempotencyKey]:
        return (tenant_id, key)

    def get(self, tenant_id: TenantId, key: IdempotencyKey, /) -> tuple[str, object] | None:
        entry = self._data.get(self._k(tenant_id, key))
        if entry is None:
            return None
        state, req_digest, obj = entry
        if state != self.DONE:
            return None
        return (req_digest, obj)

    def reserve(self, tenant_id: TenantId, key: IdempotencyKey, request_digest: str, /) -> bool:
        k = self._k(tenant_id, key)
        if k not in self._data:
            self._data[k] = (self.RESERVED, request_digest, None)
            return True
        state, _req, _obj = self._data[k]
        if state == self.FREE:
            self._data[k] = (self.RESERVED, request_digest, None)
            return True
        return False

    def complete(
        self,
        tenant_id: TenantId,
        key: IdempotencyKey,
        result_digest: str,
        result_object: object = None,
        /,
    ) -> None:
        k = self._k(tenant_id, key)
        self._data[k] = (self.DONE, result_digest, result_object)

    def release(self, tenant_id: TenantId, key: IdempotencyKey, /) -> None:
        self.release_calls.append((tenant_id, key))
        k = self._k(tenant_id, key)
        entry = self._data.get(k)
        if entry is None:
            return
        state, _req, _obj = entry
        if state == self.DONE:
            return
        if state == self.RESERVED:
            del self._data[k]


class _FakeEventPublisher(EventPublisher):
    def __init__(self) -> None:
        self.published: list[DomainEvent] = []

    def publish(self, event: DomainEvent, /) -> None:
        self.published.append(event)

    def publish_many(self, events, /) -> None:
        self.published.extend(list(events))


# ============================================================================
# Helpers de datos comunes
# ============================================================================


def _ids():
    return (
        TenantId.generate(),
        BusinessId.generate(),
        ResourceTypeId.generate(),
        ResourceId.generate(),
        LocationId.generate(),
    )


def _seed_resource_type(
    repo: FakeResourceTypeRepository,
    *,
    tenant_id: TenantId,
    business_id: BusinessId,
    resource_type_id: ResourceTypeId,
    name: str = "Default RT",
) -> ResourceTypeEntity:
    rt = ResourceTypeEntity(
        id=resource_type_id,
        tenant_id=tenant_id,
        business_id=business_id,
        name=name,
    )
    rt.clear_domain_events()
    repo.save(rt)
    return rt


def _seed_resource(
    repo: FakeResourceRepository,
    *,
    tenant_id: TenantId,
    business_id: BusinessId,
    status: ResourceStatus = ResourceStatus.ACTIVE,
    location_id: LocationId | None = None,
    resource_type_id: ResourceTypeId | None = None,
    name: str = "Mesa 1",
) -> Resource:
    rtid = resource_type_id or ResourceTypeId.generate()
    rid = ResourceId.generate()
    r = Resource(
        id=rid,
        tenant_id=tenant_id,
        business_id=business_id,
        resource_type_id=rtid,
        name=name,
        status=status,
        location_id=location_id,
    )
    r.clear_domain_events()
    repo.save(r)
    return r


# ============================================================================
# Tests
# ============================================================================


def test_create_resource_type_happy_idempotency_done() -> None:
    """Crear ResourceType con idempotency: se reserva, completa y el store
    tiene el resultado cacheado. Usa post_commit_success hook (a mano)."""
    tenant, biz, rtid, rid, loc = _ids()
    rtrepo = FakeResourceTypeRepository()
    store = FakeIdempotencyStore()

    cmd = CreateResourceType(
        tenant_id=tenant,
        business_id=biz,
        resource_type_id=rtid,
        name="Mesas",
        description="Mesas de salón",
        idempotency_key=IdempotencyKey(value="rt-create-00001"),
    )
    h = CreateResourceTypeHandler(
        resource_type_repo=rtrepo,
        idempotency_store=store,
    )
    result, events = h.handle(cmd)
    h.post_commit_success(result)

    assert isinstance(result, ResourceTypeEntity)
    assert result.id == rtid
    assert result.name == "Mesas"
    assert result.status == CatalogItemStatus.DRAFT
    assert any(isinstance(e, ResourceTypeCreated) for e in events)
    assert rtrepo.save_count == 1

    cached = store.get(tenant, IdempotencyKey(value="rt-create-00001"))
    assert cached is not None
    assert cached[1] is result


def test_create_resource_happy_without_location() -> None:
    """Crear Resource sin location: location_id=None. Requiere RT existente
    (strong validation)."""
    tenant, biz, rtid, rid, loc = _ids()
    rrepo = FakeResourceRepository()
    rtrepo = FakeResourceTypeRepository()
    _seed_resource_type(
        rtrepo,
        tenant_id=tenant,
        business_id=biz,
        resource_type_id=rtid,
        name="Mesas",
    )

    cmd = CreateResource(
        tenant_id=tenant,
        business_id=biz,
        resource_id=rid,
        resource_type_id=rtid,
        name="Mesa 5",
        location_id=None,
        capacity=0,
    )
    h = CreateResourceHandler(
        resource_repo=rrepo,
        resource_type_repo=rtrepo,
    )
    result, events = h.handle(cmd)

    assert isinstance(result, Resource)
    assert result.id == rid
    assert result.name == "Mesa 5"
    assert result.location_id is None
    assert result.status == ResourceStatus.ACTIVE
    assert any(isinstance(e, ResourceCreated) for e in events)
    assert rrepo.save_count == 1


def test_create_resource_with_location_ok() -> None:
    """Crear Resource con location_id asignado. Requiere RT existente."""
    tenant, biz, rtid, rid, loc = _ids()
    rrepo = FakeResourceRepository()
    rtrepo = FakeResourceTypeRepository()
    _seed_resource_type(
        rtrepo,
        tenant_id=tenant,
        business_id=biz,
        resource_type_id=rtid,
        name="Salones",
    )

    cmd = CreateResource(
        tenant_id=tenant,
        business_id=biz,
        resource_id=rid,
        resource_type_id=rtid,
        name="Salón Privado",
        location_id=loc,
        capacity=8,
    )
    h = CreateResourceHandler(
        resource_repo=rrepo,
        resource_type_repo=rtrepo,
    )
    result, events = h.handle(cmd)

    assert result.location_id is loc
    assert result.capacity == 8
    assert any(isinstance(e, ResourceCreated) for e in events)
    created_ev = next(e for e in events if isinstance(e, ResourceCreated))
    assert created_ev.location_id is loc


def test_activate_resource_emits_event_only_on_commit() -> None:
    """El evento ResourceActivated solo se despacha/publica DESPUÉS del commit
    (usar execute_use_case para orquestar el flujo canónico)."""
    tenant, biz, rtid, rid, loc = _ids()
    rrepo = FakeResourceRepository()
    resource = _seed_resource(
        rrepo,
        tenant_id=tenant,
        business_id=biz,
        status=ResourceStatus.INACTIVE,
        resource_type_id=rtid,
    )
    uow = FakeUnitOfWork()
    disp = DomainEventDispatcher()
    pub = _FakeEventPublisher()
    dispatched: list[DomainEvent] = []

    class _Catcher:
        def handle(self, event: DomainEvent) -> None:
            dispatched.append(event)

    disp.register(ResourceActivated, _Catcher())

    class _UCAdapter:
        """Adapta un CommandHandler a UseCaseHandler (firma compatible)."""

        def __init__(self, inner) -> None:
            self.inner = inner

        def handle(self, input, /):
            return self.inner.handle(input)

    cmd = ActivateResource(
        tenant_id=tenant,
        business_id=biz,
        resource_id=resource.id,
    )
    handler = ActivateResourceHandler(
        resource_repo=rrepo,
    )

    # Antes de execute_use_case: NO events
    assert dispatched == []
    assert pub.published == []

    result = execute_use_case(
        handler=_UCAdapter(handler),
        input=cmd,
        unit_of_work=uow,
        event_dispatcher=disp,
        event_publisher=pub,
    )

    assert result.status == ResourceStatus.ACTIVE
    assert uow.commit_count == 1
    # Solo después de commit los events salen
    assert len(dispatched) == 1
    assert isinstance(dispatched[0], ResourceActivated)
    assert len(pub.published) == 1
    assert pub.published[0] is dispatched[0]


def test_assign_resource_to_location_ok() -> None:
    """Asignar un recurso a una location (None → new_location_id)."""
    tenant, biz, rtid, rid, loc = _ids()
    rrepo = FakeResourceRepository()
    resource = _seed_resource(
        rrepo,
        tenant_id=tenant,
        business_id=biz,
        location_id=None,
        resource_type_id=rtid,
    )

    cmd = AssignResourceToLocation(
        tenant_id=tenant,
        business_id=biz,
        resource_id=resource.id,
        new_location_id=loc,
    )
    h = AssignResourceToLocationHandler(
        resource_repo=rrepo,
    )
    result, events = h.handle(cmd)

    assert result.location_id is loc
    assert len(events) == 1
    assert isinstance(events[0], ResourceAssignedToLocation)
    assert events[0].old_location_id is None
    assert events[0].new_location_id is loc


def test_unassign_resource_ok() -> None:
    """Desasignar: location_id concreta → None."""
    tenant, biz, rtid, rid, loc = _ids()
    rrepo = FakeResourceRepository()
    resource = _seed_resource(
        rrepo,
        tenant_id=tenant,
        business_id=biz,
        location_id=loc,
        resource_type_id=rtid,
    )

    cmd = AssignResourceToLocation(
        tenant_id=tenant,
        business_id=biz,
        resource_id=resource.id,
        new_location_id=None,
    )
    h = AssignResourceToLocationHandler(
        resource_repo=rrepo,
    )
    result, events = h.handle(cmd)

    assert result.location_id is None
    assert len(events) == 1
    ev = events[0]
    assert isinstance(ev, ResourceAssignedToLocation)
    assert ev.old_location_id is loc
    assert ev.new_location_id is None


def test_archive_resource_then_activate_handler_raises() -> None:
    """Archivar un Resource e intentar activarlo → InvariantViolationError
    proveniente del dominio (la invariante se rompe en Resource.activate())."""
    tenant, biz, rtid, rid, loc = _ids()
    rrepo = FakeResourceRepository()
    resource = _seed_resource(
        rrepo,
        tenant_id=tenant,
        business_id=biz,
        status=ResourceStatus.ACTIVE,
        resource_type_id=rtid,
    )

    archive_cmd = ArchiveResource(
        tenant_id=tenant,
        business_id=biz,
        resource_id=resource.id,
    )
    h_arch = ArchiveResourceHandler(
        resource_repo=rrepo,
    )
    archived_r, _ = h_arch.handle(archive_cmd)
    assert archived_r.status == ResourceStatus.ARCHIVED

    activate_cmd = ActivateResource(
        tenant_id=tenant,
        business_id=biz,
        resource_id=resource.id,
    )
    h_act = ActivateResourceHandler(
        resource_repo=rrepo,
    )
    with pytest.raises(InvariantViolationError, match="ARCHIVED"):
        h_act.handle(activate_cmd)


def test_list_active_resources_filters_correctly() -> None:
    """ListActiveResources filtra por status ACTIVE, location, resource_type."""
    tenant, biz, rtid1, rid1, loc1 = _ids()
    rtid2 = ResourceTypeId.generate()
    loc2 = LocationId.generate()

    rrepo = FakeResourceRepository()

    # ACTIVE + loc1 + rtid1 → debe aparecer
    r1 = _seed_resource(
        rrepo,
        tenant_id=tenant,
        business_id=biz,
        status=ResourceStatus.ACTIVE,
        location_id=loc1,
        resource_type_id=rtid1,
        name="A",
    )
    # INACTIVE + loc1 → no debe aparecer
    _seed_resource(
        rrepo,
        tenant_id=tenant,
        business_id=biz,
        status=ResourceStatus.INACTIVE,
        location_id=loc1,
        resource_type_id=rtid1,
        name="B",
    )
    # ACTIVE + loc2 → no debe aparecer (filtro loc1)
    _seed_resource(
        rrepo,
        tenant_id=tenant,
        business_id=biz,
        status=ResourceStatus.ACTIVE,
        location_id=loc2,
        resource_type_id=rtid1,
        name="C",
    )
    # ACTIVE + loc1 + rtid2 → no debe aparecer (filtro rtid1)
    _seed_resource(
        rrepo,
        tenant_id=tenant,
        business_id=biz,
        status=ResourceStatus.ACTIVE,
        location_id=loc1,
        resource_type_id=rtid2,
        name="D",
    )
    # ACTIVE sin location → debe aparecer si no filtramos location
    _seed_resource(
        rrepo,
        tenant_id=tenant,
        business_id=biz,
        status=ResourceStatus.ACTIVE,
        location_id=None,
        resource_type_id=rtid1,
        name="E",
    )

    h = ListActiveResourcesHandler(
        resource_repo=rrepo,
    )

    # Caso 1: location + resource_type
    q = ListActiveResources(
        tenant_id=tenant,
        business_id=biz,
        location_id=loc1,
        resource_type_id=rtid1,
    )
    result = h.handle(q)
    assert len(result) == 1
    assert result[0].id == r1.id

    # Caso 2: sin filtros → todos los ACTIVE (A, C, D, E)
    q_all = ListActiveResources(
        tenant_id=tenant,
        business_id=biz,
    )
    result_all = h.handle(q_all)
    assert len(result_all) == 4


def test_get_resource_not_found_returns_none() -> None:
    """GetResource sobre id inexistente devuelve None (no excepción)."""
    tenant, biz, rtid, rid, loc = _ids()
    rrepo = FakeResourceRepository()

    q = GetResource(
        tenant_id=tenant,
        business_id=biz,
        resource_id=ResourceId.generate(),
    )
    h = GetResourceHandler(
        resource_repo=rrepo,
    )
    assert h.handle(q) is None


def test_cross_tenant_mutate_denied_on_activate() -> None:
    """Mutación cross-tenant: handler levanta ApplicationError."""
    tenant_a = TenantId.generate()
    tenant_b = TenantId.generate()
    assert tenant_a != tenant_b
    biz = BusinessId.generate()
    rtid = ResourceTypeId.generate()

    rrepo = FakeResourceRepository()

    # Recurso perteneciente a tenant_a
    resource = _seed_resource(
        rrepo,
        tenant_id=tenant_a,
        business_id=biz,
        status=ResourceStatus.INACTIVE,
        resource_type_id=rtid,
    )

    # Command con tenant_b → debe ser rechazado
    cmd = ActivateResource(
        tenant_id=tenant_b,
        business_id=biz,
        resource_id=resource.id,
    )
    h = ActivateResourceHandler(
        resource_repo=rrepo,
    )
    with pytest.raises(ApplicationError, match="Cross-tenant mutation DENIED"):
        h.handle(cmd)


def test_create_resource_type_duplicate_key_then_noop() -> None:
    """Crear ResourceType con misma idempotency_key dos veces → la 2ª es
    no-op (devuelve el resultado original sin re-crear ni nuevos events).
    Usa post_commit_success entre llamadas."""
    tenant, biz, rtid, rid, loc = _ids()
    rtrepo = FakeResourceTypeRepository()
    store = FakeIdempotencyStore()
    key = IdempotencyKey(value="rt-dup-key-0042")

    cmd = CreateResourceType(
        tenant_id=tenant,
        business_id=biz,
        resource_type_id=rtid,
        name="Salas",
        idempotency_key=key,
    )
    h = CreateResourceTypeHandler(
        resource_type_repo=rtrepo,
        idempotency_store=store,
    )

    result1, events1 = h.handle(cmd)
    h.post_commit_success(result1)
    assert rtrepo.save_count == 1
    assert len(events1) >= 1

    # Segunda llamada con MISMA key → no-op
    result2, events2 = h.handle(cmd)
    assert result2 is result1  # Mismo objeto cacheado
    assert events2 == []  # Sin events nuevos
    assert rtrepo.save_count == 1  # No se vuelve a guardar


def test_rollback_on_repository_error() -> None:
    """Si el repositorio lanza error durante save, IdempotencyStore.release
    es invocado vía hook post_rollback para que la key no quede RESERVED."""
    tenant, biz, rtid, rid, loc = _ids()
    rtrepo = FakeResourceTypeRepository()
    _seed_resource_type(
        rtrepo,
        tenant_id=tenant,
        business_id=biz,
        resource_type_id=rtid,
        name="Mesas",
    )

    class _ExplodingResourceRepo(FakeResourceRepository):
        def save(self, resource: Resource, /) -> None:
            raise RuntimeError("DB explota durante save")

    store = FakeIdempotencyStore()
    key = IdempotencyKey(value="rollback-test-key-77")

    cmd = CreateResource(
        tenant_id=tenant,
        business_id=biz,
        resource_id=rid,
        resource_type_id=rtid,
        name="Mesa Boom",
        idempotency_key=key,
    )
    h = CreateResourceHandler(
        resource_repo=_ExplodingResourceRepo(),
        resource_type_repo=rtrepo,
        idempotency_store=store,
    )

    caught: RuntimeError | None = None
    try:
        h.handle(cmd)
    except RuntimeError as e:
        caught = e
        h.post_rollback(e)

    assert caught is not None
    assert "DB explota" in str(caught)

    # release fue llamado sobre la key vía post_rollback hook
    assert (tenant, key) in store.release_calls
    # La key no está en estado DONE
    assert store.get(tenant, key) is None
