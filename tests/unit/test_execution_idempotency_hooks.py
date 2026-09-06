"""Tests unitarios — Idempotency timeline + commit-fail idempotency + hooks.

Valida que los hooks opcionales (legacy PostCommitSuccessHook/PostRollbackHook
y el NUEVO UseCaseHandlerWithExecutionHooks.build_hooks STATLESS) produzcan
la timeline correcta:
  - OK:     reserve → commit → complete
  - FAIL:   reserve → release (NO complete)

También valida cross-tenant, cross-business, resource_type not found,
y handlers sin hooks (non-create) siguen funcionando.

Tests 1-10 usan handlers internos con el patrón LEGACY (post_commit_success /
post_rollback en self) para ver retro-compatibilidad.
Tests a-f usan los handlers REALES del código productivo y verifican el
nuevo patrón STATLESS + complete failure semantics.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from decimal import Decimal
from types import TracebackType
from typing import Any

import pytest

from universal_business.application.catalog.commands import (
    ActivateOffering,
    CreateOffering,
)
from universal_business.application.catalog.handlers import (
    ActivateOfferingHandler,
    CreateOfferingHandler,
)
from universal_business.application.errors import ApplicationError
from universal_business.application.events.dispatcher import DomainEventDispatcher
from universal_business.application.events.publisher import EventPublisher
from universal_business.application.execution import (
    UseCaseHandlerWithExecutionHooks,
    execute_use_case,
)
from universal_business.application.idempotency import (
    IdempotencyKey,
    IdempotencyStore,
)
from universal_business.application.resources.commands import CreateResource
from universal_business.application.unit_of_work import UnitOfWork
from universal_business.domain.catalog.entities import CatalogCategory, Offering
from universal_business.domain.catalog.events import (
    OfferingCreated,
)
from universal_business.domain.catalog.ports import (
    ICatalogCategoryRepository,
    IOfferingRepository,
)
from universal_business.domain.catalog.value_objects import CatalogItemStatus
from universal_business.domain.resources.entities import Resource, ResourceType
from universal_business.domain.resources.ports import (
    IResourceRepository,
    IResourceTypeRepository,
)
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CatalogCategoryId,
    LocationId,
    OfferingId,
    ResourceId,
    ResourceTypeId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money

# ============================================================================
# Helpers comunes
# ============================================================================


def _command_digest(command: object) -> str:
    raw = repr(command)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _result_digest(result: object) -> str:
    raw = str(id(result)) + repr(result)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ============================================================================
# DOUBLE: FakeIdempotencyStore con timeline (y optional complete_raises)
# ============================================================================


class FakeIdempotencyStore(IdempotencyStore):  # type: ignore[misc]
    """Implementa IdempotencyStore Protocol con timeline público.

    Opcionalmente acepta un ``global_timeline`` compartido para poder
    intercalar operaciones con otros doubles (ej. FakeUnitOfWork) y ver
    orden cronológico real.

    ``complete_raises``: si no es None, ``complete()`` lanza esa excepción
    justo DESPUÉS de registrar la entrada en timeline (para poder
    verificar que se llamó pero el estado no quedó en DONE).
    """

    def __init__(
        self,
        global_timeline: list[tuple[str, str]] | None = None,
        *,
        complete_raises: Exception | None = None,
    ) -> None:
        self.timeline: list[tuple[str, str]] = []
        self.global_timeline: list[tuple[str, str]] | None = global_timeline
        self._state: dict[tuple[TenantId, IdempotencyKey], tuple[str, str, object]] = {}
        self.complete_raises: Exception | None = complete_raises

    def _push(self, op: str, value: str) -> None:
        self.timeline.append((op, value))
        if self.global_timeline is not None:
            self.global_timeline.append((op, value))

    def get(
        self,
        tenant_id: TenantId,
        key: IdempotencyKey,
        /,
    ) -> tuple[str, object] | None:
        self._push("get", key.value)
        entry = self._state.get((tenant_id, key))
        if entry is None:
            return None
        state, req_digest, result_obj = entry
        if state == "DONE":
            return (req_digest, result_obj)
        return None

    def reserve(
        self,
        tenant_id: TenantId,
        key: IdempotencyKey,
        request_digest: str,
        /,
    ) -> bool:
        self._push("reserve", key.value)
        k = (tenant_id, key)
        if k in self._state:
            state = self._state[k][0]
            if state == "RESERVED":
                return False
            if state == "DONE":
                return False
            return False
        self._state[k] = ("RESERVED", request_digest, None)
        return True

    def complete(
        self,
        tenant_id: TenantId,
        key: IdempotencyKey,
        result_digest_str: str,
        result_object: object = None,
        /,
    ) -> None:
        self._push("complete", key.value)
        if self.complete_raises is not None:
            raise self.complete_raises
        k = (tenant_id, key)
        self._state[k] = ("DONE", result_digest_str, result_object)

    def release(
        self,
        tenant_id: TenantId,
        key: IdempotencyKey,
        /,
    ) -> None:
        self._push("release", key.value)
        k = (tenant_id, key)
        entry = self._state.get(k)
        if entry is not None:
            state = entry[0]
            if state == "RESERVED":
                del self._state[k]


# ============================================================================
# DOUBLE: FakeUnitOfWork con commit_called / commit_raises / timeline
# ============================================================================


class FakeUnitOfWork(UnitOfWork):  # type: ignore[misc]
    """UnitOfWork fake con timeline de commit + global_timeline compartido."""

    def __init__(
        self,
        global_timeline: list[tuple[str, str]] | None = None,
    ) -> None:
        self.commit_called: bool = False
        self.commit_raises: Exception | None = None
        self.rollback_called: bool = False
        self.entered: bool = False
        self.exited: bool = False
        self._committed_flag: bool = False
        self.timeline: list[tuple[str, str]] = []
        self.global_timeline: list[tuple[str, str]] | None = global_timeline

    def __enter__(self) -> FakeUnitOfWork:
        self.entered = True
        self._committed_flag = False
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
        /,
    ) -> None:
        self.exited = True
        if exc is not None or not self._committed_flag:
            self.rollback_called = True

    def commit(self) -> None:
        self.commit_called = True
        self.timeline.append(("commit", "uow"))
        if self.global_timeline is not None:
            self.global_timeline.append(("commit", "uow"))
        if self.commit_raises is not None:
            raise self.commit_raises
        self._committed_flag = True

    def rollback(self) -> None:
        self.rollback_called = True


# ============================================================================
# DOUBLE: FakeEventDispatcher con dispatched
# ============================================================================


class FakeEventDispatcher(DomainEventDispatcher):
    """Dispatcher que acumula dispatched events (usa lista, no handlers)."""

    def __init__(self) -> None:
        super().__init__()
        self.dispatched: list[DomainEvent] = []

    def dispatch_many(self, events: Sequence[DomainEvent], /) -> None:
        events_list = list(events)
        for ev in events_list:
            if not isinstance(ev, DomainEvent):
                raise TypeError(f"Expected DomainEvent, got {type(ev).__name__}")
        self.dispatched.extend(events_list)


# ============================================================================
# DOUBLE: FakeEventPublisher con published
# ============================================================================


class FakeEventPublisher(EventPublisher):  # type: ignore[misc]
    def __init__(self) -> None:
        self.published: list[DomainEvent] = []

    def publish(self, event: DomainEvent, /) -> None:
        self.published.append(event)

    def publish_many(self, events: Sequence[DomainEvent], /) -> None:
        self.published.extend(list(events))


# ============================================================================
# DOUBLE: FakeOfferingRepository (dict in-memory)
# ============================================================================


class FakeOfferingRepository(IOfferingRepository):  # type: ignore[misc]
    def __init__(self) -> None:
        self._data: dict[tuple[TenantId, OfferingId], Offering] = {}
        self.save_called_count: int = 0
        self.save_calls: list[Offering] = []

    def get(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        offering_id: OfferingId,
    ) -> Offering | None:
        direct = self._data.get((tenant_id, offering_id))
        if direct is not None:
            return direct
        for (_t_id, o_id), off in self._data.items():
            if o_id == offering_id:
                return off
        return None

    def save(self, offering: Offering, /) -> None:
        self.save_called_count += 1
        self.save_calls.append(offering)
        self._data[(offering.tenant_id, offering.id)] = offering

    def list_by_business(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId | None = None,
        status: CatalogItemStatus | None = None,
    ) -> list[Offering]:
        out: list[Offering] = []
        for (t_id, _o_id), off in self._data.items():
            if t_id != tenant_id:
                continue
            if off.business_id != business_id:
                continue
            if status is not None and off.status != status:
                continue
            out.append(off)
        return out

    def list_active(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId | None = None,
    ) -> list[Offering]:
        return self.list_by_business(
            tenant_id=tenant_id,
            business_id=business_id,
            location_id=location_id,
            status=CatalogItemStatus.ACTIVE,
        )


# ============================================================================
# DOUBLE: FakeCatalogCategoryRepository
# ============================================================================


class FakeCatalogCategoryRepository(ICatalogCategoryRepository):  # type: ignore[misc]
    def __init__(self) -> None:
        self._data: dict[tuple[TenantId, CatalogCategoryId], CatalogCategory] = {}
        self.save_called_count: int = 0
        self.save_calls: list[CatalogCategory] = []

    def get(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        category_id: CatalogCategoryId,
    ) -> CatalogCategory | None:
        return self._data.get((tenant_id, category_id))

    def save(self, category: CatalogCategory, /) -> None:
        self.save_called_count += 1
        self.save_calls.append(category)
        self._data[(category.tenant_id, category.id)] = category

    def list_by_business(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        status: CatalogItemStatus | None = None,
        parent_category_id: CatalogCategoryId | None = None,
    ) -> list[CatalogCategory]:
        out: list[CatalogCategory] = []
        for (t_id, _c_id), cat in self._data.items():
            if t_id != tenant_id:
                continue
            if cat.business_id != business_id:
                continue
            out.append(cat)
        return out


# ============================================================================
# DOUBLE: FakeResourceTypeRepository
# ============================================================================


class FakeResourceTypeRepository(IResourceTypeRepository):  # type: ignore[misc]
    def __init__(self) -> None:
        self._data: dict[tuple[TenantId, ResourceTypeId], ResourceType] = {}
        self.save_called_count: int = 0
        self.save_calls: list[ResourceType] = []

    def get(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        resource_type_id: ResourceTypeId,
    ) -> ResourceType | None:
        return self._data.get((tenant_id, resource_type_id))

    def save(self, resource_type: ResourceType, /) -> None:
        self.save_called_count += 1
        self.save_calls.append(resource_type)
        self._data[(resource_type.tenant_id, resource_type.id)] = resource_type

    def list_by_business(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        status: CatalogItemStatus | None = None,
    ) -> list[ResourceType]:
        out: list[ResourceType] = []
        for (t_id, _rt_id), rt in self._data.items():
            if t_id != tenant_id:
                continue
            if rt.business_id != business_id:
                continue
            out.append(rt)
        return out


# ============================================================================
# DOUBLE: FakeResourceRepository
# ============================================================================


class FakeResourceRepository(IResourceRepository):  # type: ignore[misc]
    def __init__(self) -> None:
        self._data: dict[tuple[TenantId, ResourceId], Resource] = {}
        self.save_called_count: int = 0
        self.save_calls: list[Resource] = []

    def get(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        resource_id: ResourceId,
    ) -> Resource | None:
        return self._data.get((tenant_id, resource_id))

    def save(self, resource: Resource, /) -> None:
        self.save_called_count += 1
        self.save_calls.append(resource)
        self._data[(resource.tenant_id, resource.id)] = resource

    def list_by_location(
        self,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId,
        status: Any = None,
        resource_type: Any = None,
        resource_type_id: ResourceTypeId | None = None,
    ) -> list[Resource]:
        out: list[Resource] = []
        for (t_id, _r_id), r in self._data.items():
            if t_id != tenant_id:
                continue
            if r.business_id != business_id:
                continue
            if r.location_id != location_id:
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
        status: Any = None,
        resource_type_id: ResourceTypeId | None = None,
    ) -> list[Resource]:
        out: list[Resource] = []
        for (t_id, _r_id), r in self._data.items():
            if t_id != tenant_id:
                continue
            if r.business_id != business_id:
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
        return self.list_by_business(
            tenant_id=tenant_id,
            business_id=business_id,
            location_id=location_id,
        )


# ============================================================================
# Handlers ADAPTADOS — PATRÓN LEGACY (compatibilidad PostCommitSuccessHook)
#   — usados por los tests 1..10
# ============================================================================

_CROSS_TENANT_MSG = "cross-tenant mutation denied"
_CROSS_BUSINESS_MSG = "cross-business mutation denied"


class HookedCreateOfferingHandler:
    """CreateOfferingHandler que usa hooks legacy post_commit_success/post_rollback.

    Usa atributos mutables en self (patrón ANTIGUO). Sirve para validar
    retro-compatibilidad del helper execute_use_case con handlers que
    implementan PostCommitSuccessHook / PostRollbackHook.
    """

    def __init__(
        self,
        *,
        offering_repository: FakeOfferingRepository,
        idempotency_store: FakeIdempotencyStore,
    ) -> None:
        self._offering_repository = offering_repository
        self._idempotency_store = idempotency_store
        self._last_tenant_id: TenantId | None = None
        self._last_key: IdempotencyKey | None = None
        self._last_result: Offering | None = None

    def handle(
        self,
        command: CreateOffering,
    ) -> tuple[Offering, Sequence[DomainEvent]]:
        id_key: IdempotencyKey | None = command.idempotency_key
        tid = command.tenant_id
        self._last_tenant_id = tid
        self._last_key = id_key

        if id_key is not None:
            reserved = self._idempotency_store.reserve(
                tid,
                id_key,
                _command_digest(command),
            )
            if not reserved:
                cached = self._idempotency_store.get(tid, id_key)
                if cached is not None:
                    result_obj = cached[1]
                    if isinstance(result_obj, Offering):
                        return (result_obj, [])
                raise ApplicationError(f"Idempotency conflict for key {id_key.value}")

        if (command.base_price is None) != (command.currency is None):
            raise ApplicationError("base_price y currency deben estar ambos presentes o ambos None")

        existing = self._offering_repository.get(
            tenant_id=tid,
            business_id=command.business_id,
            offering_id=command.offering_id,
        )
        if existing is not None:
            if id_key is not None:
                if existing.tenant_id != tid:
                    raise ApplicationError(_CROSS_TENANT_MSG)
                self._last_result = existing
                return (existing, [])
            raise ApplicationError(f"Offering {command.offering_id} already exists")

        base_price_money: Money | None = None
        if command.base_price is not None and command.currency is not None:
            base_price_money = Money(command.base_price, command.currency)

        offering = Offering(
            id=command.offering_id,
            tenant_id=tid,
            business_id=command.business_id,
            name=command.name,
            description=command.description,
            category_id=command.category_id,
            base_price=base_price_money,
            location_ids=command.location_ids or frozenset(),
        )
        offering.add_domain_event(
            OfferingCreated(
                aggregate_id=offering.id,
                tenant_id=offering.tenant_id,
                business_id=offering.business_id,
                name=offering.name,
                category_id=offering.category_id,
            )
        )
        self._offering_repository.save(offering)
        events = offering.domain_events
        offering.clear_domain_events()
        self._last_result = offering
        return (offering, list(events))

    def post_commit_success(self, result: Offering, /) -> None:
        if self._last_key is not None and self._last_tenant_id is not None:
            self._idempotency_store.complete(
                self._last_tenant_id,
                self._last_key,
                _result_digest(result),
                result,
            )

    def post_rollback(self, exc: BaseException, /) -> None:
        if self._last_key is not None and self._last_tenant_id is not None:
            self._idempotency_store.release(
                self._last_tenant_id,
                self._last_key,
            )


class StrictActivateOfferingHandler:
    """ActivateOfferingHandler con cross-tenant Y cross-business strict checks.

    NO tiene hooks (es non-create handler) — sirve para el test 10.
    """

    def __init__(self, *, offering_repository: FakeOfferingRepository) -> None:
        self._offering_repository = offering_repository

    def handle(
        self,
        command: ActivateOffering,
    ) -> tuple[Offering, Sequence[DomainEvent]]:
        offering = self._offering_repository.get(
            tenant_id=command.tenant_id,
            business_id=command.business_id,
            offering_id=command.offering_id,
        )
        if offering is None:
            raise ApplicationError(f"Offering {command.offering_id} not found")
        if offering.tenant_id != command.tenant_id:
            raise ApplicationError(_CROSS_TENANT_MSG)
        if offering.business_id != command.business_id:
            raise ApplicationError(_CROSS_BUSINESS_MSG)
        offering.activate()
        self._offering_repository.save(offering)
        events = offering.domain_events
        offering.clear_domain_events()
        return (offering, list(events))


class StrictCreateResourceHandler:
    """CreateResourceHandler con hooks legacy Y strict resource_type not found.

    Patrón ANTIGUO con hooks en self. Sirve para tests de compatibilidad.
    """

    def __init__(
        self,
        *,
        resource_repo: FakeResourceRepository,
        resource_type_repo: FakeResourceTypeRepository,
        idempotency_store: FakeIdempotencyStore,
    ) -> None:
        self._resource_repo = resource_repo
        self._resource_type_repo = resource_type_repo
        self._idempotency_store = idempotency_store
        self._last_tenant_id: TenantId | None = None
        self._last_key: IdempotencyKey | None = None

    def handle(
        self,
        command: CreateResource,
    ) -> tuple[Resource, Sequence[DomainEvent]]:
        key = command.idempotency_key
        store = self._idempotency_store
        self._last_tenant_id = command.tenant_id
        self._last_key = key

        if key is not None:
            req_digest = _command_digest(command)
            if not store.reserve(command.tenant_id, key, req_digest):
                cached = store.get(command.tenant_id, key)
                if cached is not None:
                    cached_result = cached[1]
                    assert isinstance(cached_result, Resource)
                    return (cached_result, [])
                raise ApplicationError(f"Idempotency key {key} ya está RESERVED")

        rt = self._resource_type_repo.get(
            tenant_id=command.tenant_id,
            business_id=command.business_id,
            resource_type_id=command.resource_type_id,
        )
        if rt is None:
            raise ApplicationError(f"ResourceType {command.resource_type_id} not found")
        if rt.tenant_id != command.tenant_id:
            raise ApplicationError(_CROSS_TENANT_MSG)
        if rt.business_id != command.business_id:
            raise ApplicationError(_CROSS_BUSINESS_MSG)

        r = Resource(
            id=command.resource_id,
            tenant_id=command.tenant_id,
            business_id=command.business_id,
            resource_type_id=command.resource_type_id,
            name=command.name,
            location_id=command.location_id,
            capacity=command.capacity if command.capacity > 0 else None,
        )
        events = list(r.domain_events)
        r.clear_domain_events()
        self._resource_repo.save(r)
        return (r, events)

    def post_commit_success(self, result: Resource, /) -> None:
        if self._last_key is not None and self._last_tenant_id is not None:
            self._idempotency_store.complete(
                self._last_tenant_id,
                self._last_key,
                _result_digest(result),
                result,
            )

    def post_rollback(self, exc: BaseException, /) -> None:
        if self._last_key is not None and self._last_tenant_id is not None:
            self._idempotency_store.release(
                self._last_tenant_id,
                self._last_key,
            )


# ============================================================================
# Fixtures comunes
# ============================================================================


@pytest.fixture()
def tenant_a() -> TenantId:
    return TenantId.generate()


@pytest.fixture()
def tenant_b() -> TenantId:
    return TenantId.generate()


@pytest.fixture()
def business_a() -> BusinessId:
    return BusinessId.generate()


@pytest.fixture()
def business_b() -> BusinessId:
    return BusinessId.generate()


@pytest.fixture()
def location_a() -> LocationId:
    return LocationId.generate()


@pytest.fixture()
def offering_id_1() -> OfferingId:
    return OfferingId.generate()


@pytest.fixture()
def idem_key_1() -> IdempotencyKey:
    return IdempotencyKey(value="idem-key-0001")


@pytest.fixture()
def clean_uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture()
def clean_dispatcher() -> FakeEventDispatcher:
    return FakeEventDispatcher()


@pytest.fixture()
def clean_publisher() -> FakeEventPublisher:
    return FakeEventPublisher()


@pytest.fixture()
def clean_idem_store() -> FakeIdempotencyStore:
    return FakeIdempotencyStore()


@pytest.fixture()
def clean_offering_repo() -> FakeOfferingRepository:
    return FakeOfferingRepository()


@pytest.fixture()
def clean_resource_repo() -> FakeResourceRepository:
    return FakeResourceRepository()


@pytest.fixture()
def clean_resource_type_repo() -> FakeResourceTypeRepository:
    return FakeResourceTypeRepository()


# ============================================================================
# TEST 1: test_idempotency_order_reserve_commit_complete
# ============================================================================


def test_idempotency_order_reserve_commit_complete(
    tenant_a: TenantId,
    business_a: BusinessId,
    offering_id_1: OfferingId,
    idem_key_1: IdempotencyKey,
    clean_dispatcher: FakeEventDispatcher,
    clean_publisher: FakeEventPublisher,
    clean_offering_repo: FakeOfferingRepository,
) -> None:
    global_timeline: list[tuple[str, str]] = []
    idem_store = FakeIdempotencyStore(global_timeline=global_timeline)
    uow = FakeUnitOfWork(global_timeline=global_timeline)

    handler = HookedCreateOfferingHandler(
        offering_repository=clean_offering_repo,
        idempotency_store=idem_store,
    )
    command = CreateOffering(
        tenant_id=tenant_a,
        business_id=business_a,
        offering_id=offering_id_1,
        name="Pollo a la brasa",
        idempotency_key=idem_key_1,
    )
    result = execute_use_case(
        handler=handler,
        input=command,
        unit_of_work=uow,
        event_dispatcher=clean_dispatcher,
        event_publisher=clean_publisher,
    )
    assert isinstance(result, Offering)
    assert result.id == offering_id_1

    k = idem_key_1.value
    reserve_positions: list[int] = [
        i for i, (op, v) in enumerate(global_timeline) if op == "reserve" and v == k
    ]
    commit_positions: list[int] = [
        i for i, (op, v) in enumerate(global_timeline) if op == "commit" and v == "uow"
    ]
    complete_positions: list[int] = [
        i for i, (op, v) in enumerate(global_timeline) if op == "complete" and v == k
    ]
    assert len(reserve_positions) == 1, "debe haber exactamente 1 reserve"
    assert len(commit_positions) == 1, "debe haber exactamente 1 commit"
    assert len(complete_positions) == 1, "debe haber exactamente 1 complete"

    reserve_pos = reserve_positions[0]
    commit_pos = commit_positions[0]
    complete_pos = complete_positions[0]
    assert reserve_pos < commit_pos, (
        f"reserve (pos {reserve_pos}) debe ser ANTES de commit (pos {commit_pos})"
    )
    assert commit_pos < complete_pos, (
        f"commit (pos {commit_pos}) debe ser ANTES de complete (pos {complete_pos})"
    )

    expected_timeline_head = [
        ("reserve", k),
        ("commit", "uow"),
        ("complete", k),
    ]
    timeline_for_assert = [e for e in global_timeline if e in expected_timeline_head]
    assert timeline_for_assert == expected_timeline_head, (
        f"Orden esperado reserve→commit→complete, obtenido: {timeline_for_assert}"
    )

    idem_kv = [e for e in idem_store.timeline if e[1] == k]
    ops_k = [e[0] for e in idem_kv]
    assert "release" not in ops_k


# ============================================================================
# TEST 2: test_idempotency_handler_fail_triggers_release_not_complete
# ============================================================================


def test_idempotency_handler_fail_triggers_release_not_complete(
    tenant_a: TenantId,
    business_a: BusinessId,
    offering_id_1: OfferingId,
    idem_key_1: IdempotencyKey,
    clean_uow: FakeUnitOfWork,
    clean_dispatcher: FakeEventDispatcher,
    clean_publisher: FakeEventPublisher,
    clean_idem_store: FakeIdempotencyStore,
    clean_offering_repo: FakeOfferingRepository,
) -> None:
    handler = HookedCreateOfferingHandler(
        offering_repository=clean_offering_repo,
        idempotency_store=clean_idem_store,
    )
    bad_command = CreateOffering(
        tenant_id=tenant_a,
        business_id=business_a,
        offering_id=offering_id_1,
        name="",
        idempotency_key=idem_key_1,
    )
    with pytest.raises(InvariantViolationError):
        execute_use_case(
            handler=handler,
            input=bad_command,
            unit_of_work=clean_uow,
            event_dispatcher=clean_dispatcher,
            event_publisher=clean_publisher,
        )
    k = idem_key_1.value
    ops_k = [op for (op, v) in clean_idem_store.timeline if v == k]
    assert "release" in ops_k, "debe haber release tras fallo del handler"
    assert "complete" not in ops_k, "NO debe haber complete si handler falló"


# ============================================================================
# TEST 3: test_idempotency_commit_fail_triggers_release_not_complete
# ============================================================================


def test_idempotency_commit_fail_triggers_release_not_complete(
    tenant_a: TenantId,
    business_a: BusinessId,
    offering_id_1: OfferingId,
    idem_key_1: IdempotencyKey,
    clean_dispatcher: FakeEventDispatcher,
    clean_publisher: FakeEventPublisher,
    clean_idem_store: FakeIdempotencyStore,
    clean_offering_repo: FakeOfferingRepository,
) -> None:
    uow_fail = FakeUnitOfWork()
    uow_fail.commit_raises = RuntimeError("db down")

    handler = HookedCreateOfferingHandler(
        offering_repository=clean_offering_repo,
        idempotency_store=clean_idem_store,
    )
    command = CreateOffering(
        tenant_id=tenant_a,
        business_id=business_a,
        offering_id=offering_id_1,
        name="Pollo a la brasa",
        idempotency_key=idem_key_1,
    )
    with pytest.raises(RuntimeError, match="db down"):
        execute_use_case(
            handler=handler,
            input=command,
            unit_of_work=uow_fail,
            event_dispatcher=clean_dispatcher,
            event_publisher=clean_publisher,
        )
    k = idem_key_1.value
    ops_k = [(op, v) for (op, v) in clean_idem_store.timeline if v == k]
    just_ops = [e[0] for e in ops_k]
    assert "reserve" in just_ops
    assert "release" in just_ops, "debe haber release si commit falla"
    assert "complete" not in just_ops, "NO complete si commit falla"
    assert clean_dispatcher.dispatched == []
    assert clean_publisher.published == []


# ============================================================================
# TEST 4: test_commit_fail_events_nunca_publicados
# ============================================================================


def test_commit_fail_events_nunca_publicados(
    tenant_a: TenantId,
    business_a: BusinessId,
    offering_id_1: OfferingId,
    idem_key_1: IdempotencyKey,
    clean_dispatcher: FakeEventDispatcher,
    clean_publisher: FakeEventPublisher,
    clean_idem_store: FakeIdempotencyStore,
    clean_offering_repo: FakeOfferingRepository,
) -> None:
    uow_fail = FakeUnitOfWork()
    uow_fail.commit_raises = RuntimeError("db connection lost")

    handler = HookedCreateOfferingHandler(
        offering_repository=clean_offering_repo,
        idempotency_store=clean_idem_store,
    )
    command = CreateOffering(
        tenant_id=tenant_a,
        business_id=business_a,
        offering_id=offering_id_1,
        name="Pollo a la brasa",
        base_price=Decimal("10.50"),
        currency="USD",
        idempotency_key=idem_key_1,
    )
    with pytest.raises(RuntimeError, match="db connection lost"):
        execute_use_case(
            handler=handler,
            input=command,
            unit_of_work=uow_fail,
            event_dispatcher=clean_dispatcher,
            event_publisher=clean_publisher,
        )
    assert len(clean_dispatcher.dispatched) == 0
    assert len(clean_publisher.published) == 0
    for ev in clean_dispatcher.dispatched:
        pytest.fail(f"No debió despachar: {type(ev).__name__}")
    for ev in clean_publisher.published:
        pytest.fail(f"No debió publicar: {type(ev).__name__}")


# ============================================================================
# TEST 5: test_idempotency_done_duplicate_no_second_save
# ============================================================================


def test_idempotency_done_duplicate_no_second_save(
    tenant_a: TenantId,
    business_a: BusinessId,
    offering_id_1: OfferingId,
    idem_key_1: IdempotencyKey,
    clean_dispatcher: FakeEventDispatcher,
    clean_publisher: FakeEventPublisher,
    clean_idem_store: FakeIdempotencyStore,
    clean_offering_repo: FakeOfferingRepository,
) -> None:
    handler1 = HookedCreateOfferingHandler(
        offering_repository=clean_offering_repo,
        idempotency_store=clean_idem_store,
    )
    command = CreateOffering(
        tenant_id=tenant_a,
        business_id=business_a,
        offering_id=offering_id_1,
        name="Pollo a la brasa",
        idempotency_key=idem_key_1,
    )
    uow1 = FakeUnitOfWork()
    result1 = execute_use_case(
        handler=handler1,
        input=command,
        unit_of_work=uow1,
        event_dispatcher=clean_dispatcher,
        event_publisher=clean_publisher,
    )
    save_count_after_first = clean_offering_repo.save_called_count
    assert save_count_after_first == 1

    handler2 = HookedCreateOfferingHandler(
        offering_repository=clean_offering_repo,
        idempotency_store=clean_idem_store,
    )
    uow2 = FakeUnitOfWork()
    disp2 = FakeEventDispatcher()
    pub2 = FakeEventPublisher()
    result2 = execute_use_case(
        handler=handler2,
        input=command,
        unit_of_work=uow2,
        event_dispatcher=disp2,
        event_publisher=pub2,
    )
    assert clean_offering_repo.save_called_count == 1, (
        "segunda llamada idempotente NO debe volver a hacer save del repo"
    )
    assert result1.id == result2.id
    assert isinstance(result2, Offering)
    assert result2.name == "Pollo a la brasa"


# ============================================================================
# TEST 6: test_cross_tenant_mutation_denied_offering
# ============================================================================


def test_cross_tenant_mutation_denied_offering(
    tenant_a: TenantId,
    tenant_b: TenantId,
    business_a: BusinessId,
    offering_id_1: OfferingId,
    clean_dispatcher: FakeEventDispatcher,
    clean_publisher: FakeEventPublisher,
    clean_offering_repo: FakeOfferingRepository,
) -> None:
    pre_handler = HookedCreateOfferingHandler(
        offering_repository=clean_offering_repo,
        idempotency_store=FakeIdempotencyStore(),
    )
    uow_pre = FakeUnitOfWork()
    disp_pre = FakeEventDispatcher()
    pub_pre = FakeEventPublisher()
    create_cmd = CreateOffering(
        tenant_id=tenant_a,
        business_id=business_a,
        offering_id=offering_id_1,
        name="Pollo a la brasa",
        idempotency_key=IdempotencyKey(value="create-tenant-a-001"),
    )
    execute_use_case(
        handler=pre_handler,
        input=create_cmd,
        unit_of_work=uow_pre,
        event_dispatcher=disp_pre,
        event_publisher=pub_pre,
    )

    saved = clean_offering_repo.get(
        tenant_id=tenant_a,
        business_id=business_a,
        offering_id=offering_id_1,
    )
    assert saved is not None
    assert saved.tenant_id == tenant_a

    activate_handler = StrictActivateOfferingHandler(
        offering_repository=clean_offering_repo,
    )
    cross_cmd = ActivateOffering(
        tenant_id=tenant_b,
        business_id=business_a,
        offering_id=offering_id_1,
    )
    uow_act = FakeUnitOfWork()
    with pytest.raises(ApplicationError, match=_CROSS_TENANT_MSG):
        execute_use_case(
            handler=activate_handler,
            input=cross_cmd,
            unit_of_work=uow_act,
            event_dispatcher=clean_dispatcher,
            event_publisher=clean_publisher,
        )


# ============================================================================
# TEST 7: test_cross_business_same_tenant_denied_offering
# ============================================================================


def test_cross_business_same_tenant_denied_offering(
    tenant_a: TenantId,
    business_a: BusinessId,
    business_b: BusinessId,
    offering_id_1: OfferingId,
    clean_dispatcher: FakeEventDispatcher,
    clean_publisher: FakeEventPublisher,
    clean_offering_repo: FakeOfferingRepository,
) -> None:
    pre_handler = HookedCreateOfferingHandler(
        offering_repository=clean_offering_repo,
        idempotency_store=FakeIdempotencyStore(),
    )
    uow_pre = FakeUnitOfWork()
    create_cmd = CreateOffering(
        tenant_id=tenant_a,
        business_id=business_a,
        offering_id=offering_id_1,
        name="Pollo a la brasa",
        idempotency_key=IdempotencyKey(value="create-biz-a-0002"),
    )
    execute_use_case(
        handler=pre_handler,
        input=create_cmd,
        unit_of_work=uow_pre,
        event_dispatcher=FakeEventDispatcher(),
        event_publisher=FakeEventPublisher(),
    )

    activate_handler = StrictActivateOfferingHandler(
        offering_repository=clean_offering_repo,
    )
    cross_biz_cmd = ActivateOffering(
        tenant_id=tenant_a,
        business_id=business_b,
        offering_id=offering_id_1,
    )
    uow_act = FakeUnitOfWork()
    with pytest.raises(ApplicationError, match=_CROSS_BUSINESS_MSG):
        execute_use_case(
            handler=activate_handler,
            input=cross_biz_cmd,
            unit_of_work=uow_act,
            event_dispatcher=clean_dispatcher,
            event_publisher=clean_publisher,
        )


# ============================================================================
# TEST 8: test_same_tenant_same_business_allowed
# ============================================================================


def test_same_tenant_same_business_allowed(
    tenant_a: TenantId,
    business_a: BusinessId,
    offering_id_1: OfferingId,
    clean_dispatcher: FakeEventDispatcher,
    clean_publisher: FakeEventPublisher,
    clean_offering_repo: FakeOfferingRepository,
) -> None:
    pre_handler = HookedCreateOfferingHandler(
        offering_repository=clean_offering_repo,
        idempotency_store=FakeIdempotencyStore(),
    )
    uow_pre = FakeUnitOfWork()
    create_cmd = CreateOffering(
        tenant_id=tenant_a,
        business_id=business_a,
        offering_id=offering_id_1,
        name="Pollo a la brasa",
        idempotency_key=IdempotencyKey(value="create-ok-0003"),
    )
    execute_use_case(
        handler=pre_handler,
        input=create_cmd,
        unit_of_work=uow_pre,
        event_dispatcher=FakeEventDispatcher(),
        event_publisher=FakeEventPublisher(),
    )

    activate_handler = StrictActivateOfferingHandler(
        offering_repository=clean_offering_repo,
    )
    ok_cmd = ActivateOffering(
        tenant_id=tenant_a,
        business_id=business_a,
        offering_id=offering_id_1,
    )
    uow_act = FakeUnitOfWork()
    result = execute_use_case(
        handler=activate_handler,
        input=ok_cmd,
        unit_of_work=uow_act,
        event_dispatcher=clean_dispatcher,
        event_publisher=clean_publisher,
    )
    assert isinstance(result, Offering)
    assert result.status == CatalogItemStatus.ACTIVE
    assert len(clean_dispatcher.dispatched) >= 1
    assert len(clean_publisher.published) >= 1
    assert uow_act.commit_called is True


# ============================================================================
# TEST 9: test_resource_type_not_found_on_create_resource
# ============================================================================


def test_resource_type_not_found_on_create_resource(
    tenant_a: TenantId,
    business_a: BusinessId,
    clean_resource_repo: FakeResourceRepository,
    clean_resource_type_repo: FakeResourceTypeRepository,
    clean_idem_store: FakeIdempotencyStore,
    clean_dispatcher: FakeEventDispatcher,
    clean_publisher: FakeEventPublisher,
) -> None:
    unknown_rt_id = ResourceTypeId.generate()

    handler = StrictCreateResourceHandler(
        resource_repo=clean_resource_repo,
        resource_type_repo=clean_resource_type_repo,
        idempotency_store=clean_idem_store,
    )
    cmd = CreateResource(
        tenant_id=tenant_a,
        business_id=business_a,
        resource_id=ResourceId.generate(),
        resource_type_id=unknown_rt_id,
        name="Silla barbero 1",
        idempotency_key=IdempotencyKey(value="create-res-0001"),
    )
    uow = FakeUnitOfWork()
    with pytest.raises(ApplicationError) as exc_info:
        execute_use_case(
            handler=handler,
            input=cmd,
            unit_of_work=uow,
            event_dispatcher=clean_dispatcher,
            event_publisher=clean_publisher,
        )
    err_msg = str(exc_info.value)
    assert "ResourceType" in err_msg
    assert "not found" in err_msg

    assert clean_resource_repo.save_called_count == 0, (
        "resource_repo.save NUNCA debe llamarse si resource_type no existe"
    )
    assert len(clean_resource_repo.save_calls) == 0


# ============================================================================
# TEST 10: test_no_post_commit_hooks_in_non_create_handlers
# ============================================================================


def test_no_post_commit_hooks_in_non_create_handlers(
    tenant_a: TenantId,
    business_a: BusinessId,
    offering_id_1: OfferingId,
    clean_dispatcher: FakeEventDispatcher,
    clean_publisher: FakeEventPublisher,
    clean_offering_repo: FakeOfferingRepository,
) -> None:
    pre_handler = HookedCreateOfferingHandler(
        offering_repository=clean_offering_repo,
        idempotency_store=FakeIdempotencyStore(),
    )
    create_cmd = CreateOffering(
        tenant_id=tenant_a,
        business_id=business_a,
        offering_id=offering_id_1,
        name="Pollo a la brasa",
        idempotency_key=IdempotencyKey(value="create-for-test10"),
    )
    execute_use_case(
        handler=pre_handler,
        input=create_cmd,
        unit_of_work=FakeUnitOfWork(),
        event_dispatcher=FakeEventDispatcher(),
        event_publisher=FakeEventPublisher(),
    )

    activate_handler = StrictActivateOfferingHandler(
        offering_repository=clean_offering_repo,
    )
    assert not hasattr(activate_handler, "post_commit_success"), (
        "Handler non-create NO debe implementar post_commit_success"
    )
    assert not hasattr(activate_handler, "post_rollback"), (
        "Handler non-create NO debe implementar post_rollback"
    )

    cmd = ActivateOffering(
        tenant_id=tenant_a,
        business_id=business_a,
        offering_id=offering_id_1,
    )
    uow = FakeUnitOfWork()
    result = execute_use_case(
        handler=activate_handler,
        input=cmd,
        unit_of_work=uow,
        event_dispatcher=clean_dispatcher,
        event_publisher=clean_publisher,
    )
    assert isinstance(result, Offering)
    assert result.status == CatalogItemStatus.ACTIVE
    assert uow.commit_called is True
    assert len(clean_publisher.published) >= 1
    assert len(clean_dispatcher.dispatched) >= 1


# ============================================================================
# TESTS NUEVOS — Patrón STATLESS (UseCaseHandlerWithExecutionHooks)
# ============================================================================


def test_stateless_handler_two_concurrent_executions_independent_keys(
    tenant_a: TenantId,
    business_a: BusinessId,
    clean_offering_repo: FakeOfferingRepository,
    clean_dispatcher: FakeEventDispatcher,
    clean_publisher: FakeEventPublisher,
) -> None:
    """(a) Handler reutilizado, dos ejecuciones con keys A y B distintas.

    Verifica timeline: reserve_A → commit → complete_A ; reserve_B → commit → complete_B
    NO hay interferencia: no se llama release ni complete con la key equivocada.
    """
    global_timeline: list[tuple[str, str]] = []
    idem_store = FakeIdempotencyStore(global_timeline=global_timeline)

    handler = CreateOfferingHandler(
        offering_repository=clean_offering_repo,
        idempotency_store=idem_store,
    )

    key_a = IdempotencyKey(value="stateless-A")
    key_b = IdempotencyKey(value="stateless-B")
    oid_a = OfferingId.generate()
    oid_b = OfferingId.generate()

    cmd_a = CreateOffering(
        tenant_id=tenant_a,
        business_id=business_a,
        offering_id=oid_a,
        name="Oferta A",
        idempotency_key=key_a,
    )
    cmd_b = CreateOffering(
        tenant_id=tenant_a,
        business_id=business_a,
        offering_id=oid_b,
        name="Oferta B",
        idempotency_key=key_b,
    )

    uow_a = FakeUnitOfWork(global_timeline=global_timeline)
    result_a = execute_use_case(
        handler=handler,
        input=cmd_a,
        unit_of_work=uow_a,
        event_dispatcher=clean_dispatcher,
        event_publisher=clean_publisher,
    )

    disp_b = FakeEventDispatcher()
    pub_b = FakeEventPublisher()
    uow_b = FakeUnitOfWork(global_timeline=global_timeline)
    result_b = execute_use_case(
        handler=handler,
        input=cmd_b,
        unit_of_work=uow_b,
        event_dispatcher=disp_b,
        event_publisher=pub_b,
    )

    assert isinstance(result_a, Offering) and result_a.id == oid_a
    assert isinstance(result_b, Offering) and result_b.id == oid_b

    ka, kb = key_a.value, key_b.value

    ops_a = [(op, v) for (op, v) in global_timeline if v == ka]
    ops_b = [(op, v) for (op, v) in global_timeline if v == kb]

    assert [op for op, _ in ops_a] == ["reserve", "complete"], (
        f"Ops A deben ser reserve+complete, got {ops_a}"
    )
    assert [op for op, _ in ops_b] == ["reserve", "complete"], (
        f"Ops B deben ser reserve+complete, got {ops_b}"
    )
    assert "release" not in [op for op, _ in global_timeline]

    for op, v in global_timeline:
        if op == "complete" and v == ka:
            break_a_pos = global_timeline.index((op, v))
    reserve_b_pos = global_timeline.index(("reserve", kb))
    assert reserve_b_pos > break_a_pos, (
        "Ejecución A debe completar (al menos commit) ANTES de que empiece B en secuencial"
    )


def test_stateless_handler_rollback_a_no_release_b(
    tenant_a: TenantId,
    business_a: BusinessId,
    clean_offering_repo: FakeOfferingRepository,
    clean_dispatcher: FakeEventDispatcher,
    clean_publisher: FakeEventPublisher,
) -> None:
    """(b) Rollback de A NO afecta a B. Handler compartido.

    Ejecución A: uow.commit_raises → debe release_A.
    Ejecución B: success → complete_B OK.
    Verifica: release de A NO liberó key de B.
    """
    idem_store = FakeIdempotencyStore()
    handler = CreateOfferingHandler(
        offering_repository=clean_offering_repo,
        idempotency_store=idem_store,
    )

    key_a = IdempotencyKey(value="rollback-A")
    key_b = IdempotencyKey(value="success-B")
    oid_a = OfferingId.generate()
    oid_b = OfferingId.generate()

    cmd_a = CreateOffering(
        tenant_id=tenant_a,
        business_id=business_a,
        offering_id=oid_a,
        name="Fallo A",
        idempotency_key=key_a,
    )
    cmd_b = CreateOffering(
        tenant_id=tenant_a,
        business_id=business_a,
        offering_id=oid_b,
        name="Exito B",
        idempotency_key=key_b,
    )

    uow_a = FakeUnitOfWork()
    uow_a.commit_raises = RuntimeError("boom-A")
    with pytest.raises(RuntimeError, match="boom-A"):
        execute_use_case(
            handler=handler,
            input=cmd_a,
            unit_of_work=uow_a,
            event_dispatcher=clean_dispatcher,
            event_publisher=clean_publisher,
        )

    disp_b = FakeEventDispatcher()
    pub_b = FakeEventPublisher()
    result_b = execute_use_case(
        handler=handler,
        input=cmd_b,
        unit_of_work=FakeUnitOfWork(),
        event_dispatcher=disp_b,
        event_publisher=pub_b,
    )

    ka, kb = key_a.value, key_b.value
    ops_a = [op for (op, v) in idem_store.timeline if v == ka]
    ops_b = [op for (op, v) in idem_store.timeline if v == kb]

    assert ops_a == ["reserve", "release"], f"esperado reserve+release A, got {ops_a}"
    assert ops_b == ["reserve", "complete"], f"esperado reserve+complete B, got {ops_b}"
    assert isinstance(result_b, Offering)
    assert result_b.id == oid_b


def test_stateless_handler_commit_a_no_complete_b(
    tenant_a: TenantId,
    business_a: BusinessId,
    clean_offering_repo: FakeOfferingRepository,
) -> None:
    """(c) Dos éxitos secuenciales sobre MISMA instancia handler.

    complete_A y complete_B ambas llamadas correctas con sus keys.
    Ninguna ejecución pisa el closure de la otra.
    """
    idem_store = FakeIdempotencyStore()
    handler = CreateOfferingHandler(
        offering_repository=clean_offering_repo,
        idempotency_store=idem_store,
    )

    key_a = IdempotencyKey(value="ok-C-A-001")
    key_b = IdempotencyKey(value="ok-C-B-001")
    oid_a = OfferingId.generate()
    oid_b = OfferingId.generate()

    result_a = execute_use_case(
        handler=handler,
        input=CreateOffering(
            tenant_id=tenant_a,
            business_id=business_a,
            offering_id=oid_a,
            name="A",
            idempotency_key=key_a,
        ),
        unit_of_work=FakeUnitOfWork(),
        event_dispatcher=FakeEventDispatcher(),
        event_publisher=FakeEventPublisher(),
    )
    result_b = execute_use_case(
        handler=handler,
        input=CreateOffering(
            tenant_id=tenant_a,
            business_id=business_a,
            offering_id=oid_b,
            name="B",
            idempotency_key=key_b,
        ),
        unit_of_work=FakeUnitOfWork(),
        event_dispatcher=FakeEventDispatcher(),
        event_publisher=FakeEventPublisher(),
    )

    ka, kb = key_a.value, key_b.value
    completes = [(op, v) for (op, v) in idem_store.timeline if op == "complete"]
    assert completes == [("complete", ka), ("complete", kb)], (
        f"completes deben ser A luego B: {completes}"
    )
    assert result_a.id == oid_a
    assert result_b.id == oid_b
    assert not any(op == "release" for op, _ in idem_store.timeline)


def test_stateless_reuse_handler_no_pending_state(
    tenant_a: TenantId,
    business_a: BusinessId,
    clean_offering_repo: FakeOfferingRepository,
) -> None:
    """(d) Handler compartido, 2 comandos diferentes.

    Después de ejecución 1 (success OK) no hay ningún state "pendiente"
    que afecte a la ejecución 2. Resultados correctos.
    """
    idem_store = FakeIdempotencyStore()
    handler = CreateOfferingHandler(
        offering_repository=clean_offering_repo,
        idempotency_store=idem_store,
    )
    assert not hasattr(handler, "_idem_pending"), (
        "El handler REAL NUEVO no debe tener atributo _idem_pending"
    )

    oid_1 = OfferingId.generate()
    oid_2 = OfferingId.generate()
    key_1 = IdempotencyKey(value="reuse-0001")
    key_2 = IdempotencyKey(value="reuse-0002")

    r1 = execute_use_case(
        handler=handler,
        input=CreateOffering(
            tenant_id=tenant_a,
            business_id=business_a,
            offering_id=oid_1,
            name="Servicio 1",
            idempotency_key=key_1,
            base_price=Decimal("25.00"),
            currency="EUR",
        ),
        unit_of_work=FakeUnitOfWork(),
        event_dispatcher=FakeEventDispatcher(),
        event_publisher=FakeEventPublisher(),
    )
    r2 = execute_use_case(
        handler=handler,
        input=CreateOffering(
            tenant_id=tenant_a,
            business_id=business_a,
            offering_id=oid_2,
            name="Servicio 2 — sin precio",
            idempotency_key=key_2,
        ),
        unit_of_work=FakeUnitOfWork(),
        event_dispatcher=FakeEventDispatcher(),
        event_publisher=FakeEventPublisher(),
    )

    assert isinstance(r1, Offering) and r1.id == oid_1
    assert isinstance(r2, Offering) and r2.id == oid_2
    assert r1.base_price is not None
    assert r2.base_price is None

    completes = [v for (op, v) in idem_store.timeline if op == "complete"]
    assert set(completes) == {key_1.value, key_2.value}
    assert len(completes) == 2


def test_non_create_handler_no_build_hooks_method(
    tenant_a: TenantId,
    business_a: BusinessId,
    clean_offering_repo: FakeOfferingRepository,
) -> None:
    """(e) ActivateOfferingHandler no implementa UseCaseHandlerWithExecutionHooks.

    isinstance devuelve False; el handler sigue funcionando normalmente a
    través del flujo estándar (sin build_hooks).
    """
    pre_store = FakeIdempotencyStore()
    pre_handler = CreateOfferingHandler(
        offering_repository=clean_offering_repo,
        idempotency_store=pre_store,
    )
    oid = OfferingId.generate()
    execute_use_case(
        handler=pre_handler,
        input=CreateOffering(
            tenant_id=tenant_a,
            business_id=business_a,
            offering_id=oid,
            name="Existente",
            idempotency_key=IdempotencyKey(value="pre-create-e"),
        ),
        unit_of_work=FakeUnitOfWork(),
        event_dispatcher=FakeEventDispatcher(),
        event_publisher=FakeEventPublisher(),
    )

    activate_handler = ActivateOfferingHandler(
        offering_repository=clean_offering_repo,
    )

    assert isinstance(activate_handler, UseCaseHandlerWithExecutionHooks) is False, (
        "ActivateOfferingHandler NO debe satisfacer UseCaseHandlerWithExecutionHooks"
    )
    assert not hasattr(activate_handler, "build_hooks")

    disp = FakeEventDispatcher()
    pub = FakeEventPublisher()
    uow = FakeUnitOfWork()
    result = execute_use_case(
        handler=activate_handler,
        input=ActivateOffering(
            tenant_id=tenant_a,
            business_id=business_a,
            offering_id=oid,
        ),
        unit_of_work=uow,
        event_dispatcher=disp,
        event_publisher=pub,
    )
    assert isinstance(result, Offering)
    assert result.status == CatalogItemStatus.ACTIVE
    assert uow.commit_called is True
    assert len(disp.dispatched) >= 1
    assert len(pub.published) >= 1


def test_complete_failure_after_commit_no_release(
    tenant_a: TenantId,
    business_a: BusinessId,
    clean_offering_repo: FakeOfferingRepository,
    clean_dispatcher: FakeEventDispatcher,
    clean_publisher: FakeEventPublisher,
) -> None:
    """(f) Complete failure semantics.

    idem_store.complete() lanza DESPUÉS de uow.commit() exitoso.
    Verifica:
      - uow.commit_called=True (dominio COMMITTEADO, no rollback).
      - store.release NUNCA invocado.
      - Error de complete() se PROPAGA hacia arriba.
      - events dispatch y publish SÍ se ejecutan (commit OK).
      - En idem_store la key sigue en estado RESERVED (no pasó a DONE).
    """
    complete_exc = RuntimeError("idempotency backend unavailable")
    idem_store = FakeIdempotencyStore(complete_raises=complete_exc)
    handler = CreateOfferingHandler(
        offering_repository=clean_offering_repo,
        idempotency_store=idem_store,
    )

    key_fail = IdempotencyKey(value="complete-fail-f")
    uow = FakeUnitOfWork()

    with pytest.raises(RuntimeError, match="idempotency backend unavailable"):
        execute_use_case(
            handler=handler,
            input=CreateOffering(
                tenant_id=tenant_a,
                business_id=business_a,
                offering_id=OfferingId.generate(),
                name="Oferta X",
                idempotency_key=key_fail,
            ),
            unit_of_work=uow,
            event_dispatcher=clean_dispatcher,
            event_publisher=clean_publisher,
        )

    assert uow.commit_called is True, "uow.commit se llamó antes del fallo"
    assert uow.rollback_called is False, "commit OK → no hay rollback (imposible post-commit)"
    kf = key_fail.value
    ops = [op for (op, v) in idem_store.timeline if v == kf]
    assert "reserve" in ops
    assert "complete" in ops, "complete() se intentó llamar y falló"
    assert "release" not in ops, "complete() no debe disparar release: la key debe quedar RESERVED"
    assert len(clean_dispatcher.dispatched) >= 1, "events se despachan aunque complete falle"
    assert len(clean_publisher.published) >= 1, "events se publican aunque complete falle"
