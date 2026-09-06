"""Tests unitarios — Application layer Catalog subpackage (Gate 0.3).

Implementa doubles en memoria de:
  - FakeOfferingRepository → dict keyed by (tenant_id, offering_id)
  - FakeCatalogCategoryRepository → dict keyed by (tenant_id, category_id)
  - FakeUnitOfWork → context manager con flags de commit/rollback
  - FakeIdempotencyStore → FREE / RESERVED / DONE
  - FakeEventPublisher → acumula published events

Los tests siguen el patrón «Arrange / Act / Assert» y comprueban happy paths,
sad paths, cross-tenant, idempotencia, rollback en excepciones y semántica de
eventos post-commit.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from types import TracebackType

import pytest

from universal_business.application import (
    DomainEventDispatcher,
    execute_use_case,
)
from universal_business.application.catalog.commands import (
    ActivateOffering,
    ArchiveOffering,
    ChangeOfferingPrice,
    CreateCatalogCategory,
    CreateOffering,
    DeactivateOffering,
)
from universal_business.application.catalog.handlers import (
    ActivateOfferingHandler,
    ArchiveOfferingHandler,
    ChangeOfferingPriceHandler,
    CreateCatalogCategoryHandler,
    CreateOfferingHandler,
    DeactivateOfferingHandler,
    GetOfferingHandler,
    ListActiveOfferingsHandler,
)
from universal_business.application.catalog.queries import GetOffering, ListActiveOfferings
from universal_business.application.errors import (
    ApplicationError,
)
from universal_business.application.idempotency import (
    IdempotencyKey,
)
from universal_business.domain.catalog.entities import CatalogCategory, Offering
from universal_business.domain.catalog.events import (
    OfferingActivated,
    OfferingCreated,
    OfferingPriceChanged,
)
from universal_business.domain.catalog.value_objects import CatalogItemStatus
from universal_business.domain.shared.errors import (
    InvariantViolationError,
    MoneyCurrencyMismatchError,
)
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CatalogCategoryId,
    LocationId,
    OfferingId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Currency, Money

# ============================================================================
# Fake doubles (solo tests)
# ============================================================================


class FakeOfferingRepository:
    """DOBLE en memoria del IOfferingRepository Protocol."""

    def __init__(self) -> None:
        self._data: dict[tuple[TenantId, OfferingId], Offering] = {}
        self.save_calls: list[Offering] = []
        self.fail_on_save: bool = False

    def get(
        self,
        /,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        offering_id: OfferingId,
    ) -> Offering | None:
        return self._data.get((tenant_id, offering_id))

    def save(self, offering: Offering, /) -> None:
        if self.fail_on_save:
            raise RuntimeError("simulated DB failure on Offering.save")
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
            if location_id is not None and location_id not in off.location_ids:
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


class FakeCatalogCategoryRepository:
    """DOBLE en memoria del ICatalogCategoryRepository Protocol."""

    def __init__(self) -> None:
        self._data: dict[tuple[TenantId, CatalogCategoryId], CatalogCategory] = {}
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
            if status is not None and cat.status != status:
                continue
            if parent_category_id is not None and cat.parent_category_id != parent_category_id:
                continue
            out.append(cat)
        return out


class FakeUnitOfWork:
    """DOBLE del UnitOfWork Protocol con flags y counters."""

    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0
        self.entered = False
        self.exited = False
        self.fail_on_commit: bool = False
        self._committed = False
        self._rolledback = False

    def __enter__(self) -> FakeUnitOfWork:
        self.entered = True
        self._committed = False
        self._rolledback = False
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
        /,
    ) -> None:
        self.exited = True
        if exc is not None or not self._committed:
            self.rollback()

    def commit(self) -> None:
        if self._rolledback:
            return
        if self.fail_on_commit:
            raise RuntimeError("simulated commit failure")
        self._committed = True
        self.commit_count += 1

    def rollback(self) -> None:
        if self._rolledback:
            return
        self._rolledback = True
        self.rollback_count += 1


class FakeIdempotencyStore:
    """DOBLE en memoria del IdempotencyStore Protocol."""

    FREE = "FREE"
    RESERVED = "RESERVED"
    DONE = "DONE"

    def __init__(self) -> None:
        self._data: dict[tuple[TenantId, IdempotencyKey], tuple[str, str, object]] = {}

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

    def reserve(
        self,
        tenant_id: TenantId,
        key: IdempotencyKey,
        request_digest: str,
        /,
    ) -> bool:
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
        k = self._k(tenant_id, key)
        entry = self._data.get(k)
        if entry is None:
            return
        state, _req, _obj = entry
        if state == self.DONE:
            return
        if state == self.RESERVED:
            del self._data[k]


class FakeEventPublisher:
    """DOBLE del EventPublisher Protocol que acumula eventos."""

    def __init__(self) -> None:
        self.published: list[DomainEvent] = []

    def publish(self, event: DomainEvent, /) -> None:
        self.published.append(event)

    def publish_many(self, events: Sequence[DomainEvent], /) -> None:
        self.published.extend(list(events))


# ============================================================================
# Helpers comunes a varios tests
# ============================================================================


def _new_idempotency_key(suffix: str = "00000001") -> IdempotencyKey:
    return IdempotencyKey(value=f"idemp-{suffix}")


def _build_base_offering_command(
    *,
    tenant_id: TenantId,
    business_id: BusinessId,
    offering_id: OfferingId | None = None,
    idempotency_key: IdempotencyKey | None = None,
    base_price: Decimal | None = None,
    currency: str | Currency | None = None,
    location_ids: frozenset[LocationId] | None = None,
) -> CreateOffering:
    return CreateOffering(
        tenant_id=tenant_id,
        business_id=business_id,
        offering_id=offering_id or OfferingId.generate(),
        name="Hamburguesa Clásica",
        description="Con queso y papas",
        base_price=base_price,
        currency=currency,
        location_ids=location_ids,
        idempotency_key=idempotency_key,
    )


# ============================================================================
# Tests CreateOffering
# ============================================================================


def test_create_offering_happy_path_idempotency_reserved_then_done() -> None:
    """Flujo happy: reserve → crea → complete. Estado final DONE + offering persistido."""
    tid = TenantId.generate()
    bid = BusinessId.generate()
    oid = OfferingId.generate()
    key = _new_idempotency_key("create-off-happy-01")

    repo = FakeOfferingRepository()
    store = FakeIdempotencyStore()
    uow = FakeUnitOfWork()
    disp = DomainEventDispatcher()
    pub = FakeEventPublisher()
    captured: list[DomainEvent] = []

    class _Listener:
        def handle(self, event: DomainEvent) -> None:
            captured.append(event)

    disp.register(OfferingCreated, _Listener())

    handler = CreateOfferingHandler(
        offering_repository=repo,
        idempotency_store=store,
    )
    cmd = _build_base_offering_command(
        tenant_id=tid,
        business_id=bid,
        offering_id=oid,
        idempotency_key=key,
        base_price=Decimal("15.99"),
        currency="USD",
    )

    result = execute_use_case(
        handler=handler,
        input=cmd,
        unit_of_work=uow,
        event_dispatcher=disp,
        event_publisher=pub,
    )

    # Resultado correcto
    assert isinstance(result, Offering)
    assert result.id == oid
    assert result.tenant_id == tid
    assert result.name == "Hamburguesa Clásica"
    assert result.base_price == Money(Decimal("15.99"), "USD")
    assert result.status == CatalogItemStatus.DRAFT

    # UoW: commited, no rollback
    assert uow.commit_count == 1
    assert uow.rollback_count == 0

    # Idempotency: DONE
    entry = store.get(tid, key)
    assert entry is not None, "La key debe estar en estado DONE tras complete()"
    assert entry[1] is result

    # Repo: persisted
    saved = repo.get(tenant_id=tid, business_id=bid, offering_id=oid)
    assert saved is not None
    assert saved.id == oid

    # Events post-commit: dispatcher y publisher reciben OfferingCreated
    assert len(captured) == 1
    assert isinstance(captured[0], OfferingCreated)
    assert captured[0].aggregate_id == oid
    assert len(pub.published) == 1
    assert isinstance(pub.published[0], OfferingCreated)


def test_create_offering_cross_tenant_denied() -> None:
    """Mutación cross-tenant: handler debe levantar ApplicationError antes de commit."""
    tid_a = TenantId.generate()
    tid_b = TenantId.generate()
    bid = BusinessId.generate()
    oid = OfferingId.generate()

    repo = FakeOfferingRepository()
    # Pre-insertamos un offering del tenant A
    pre_existing = Offering(
        id=oid,
        tenant_id=tid_a,
        business_id=bid,
        name="Pre-existente A",
    )
    repo.save(pre_existing)

    store = FakeIdempotencyStore()
    key = _new_idempotency_key("cross-tenant-01")
    # Reservamos la key para el tenant B (quien intentará «crear» el offering)
    store.reserve(tid_b, key, "fake-digest")

    handler = CreateOfferingHandler(
        offering_repository=repo,
        idempotency_store=store,
    )
    cmd = CreateOffering(
        tenant_id=tid_b,
        business_id=bid,
        offering_id=oid,
        name="Intentando sobrescribir de A",
        idempotency_key=key,
    )

    with pytest.raises(ApplicationError, match="cross-tenant"):
        handler.handle(cmd)


def test_create_offering_repository_rollback_on_exception() -> None:
    """Si el save lanza excepción → el UoW __exit__ hace rollback automático."""
    tid = TenantId.generate()
    bid = BusinessId.generate()

    repo = FakeOfferingRepository()
    repo.fail_on_save = True
    store = FakeIdempotencyStore()
    uow = FakeUnitOfWork()
    disp = DomainEventDispatcher()
    pub = FakeEventPublisher()

    handler = CreateOfferingHandler(
        offering_repository=repo,
        idempotency_store=store,
    )
    cmd = _build_base_offering_command(
        tenant_id=tid,
        business_id=bid,
        idempotency_key=_new_idempotency_key("rollback-01"),
    )

    with pytest.raises(RuntimeError, match="simulated DB failure"):
        execute_use_case(
            handler=handler,
            input=cmd,
            unit_of_work=uow,
            event_dispatcher=disp,
            event_publisher=pub,
        )

    # UoW: rollback, no commit
    assert uow.commit_count == 0
    assert uow.rollback_count == 1

    # Idempotency: key fue liberada (release) y no está DONE
    assert store.get(tid, cmd.idempotency_key) is None

    # Events: no se publicó nada
    assert pub.published == []


# ============================================================================
# Tests Activate/Deactivate/Archive Offering
# ============================================================================


def test_activate_offering_happy_emits_event_after_commit() -> None:
    """Eventos SOLO se publican DESPUÉS de commit; si handler se llama a pelo, no hay publish."""
    tid = TenantId.generate()
    bid = BusinessId.generate()
    oid = OfferingId.generate()

    repo = FakeOfferingRepository()
    repo.save(
        Offering(
            id=oid,
            tenant_id=tid,
            business_id=bid,
            name="Producto DRAFT",
            status=CatalogItemStatus.DRAFT,
        )
    )

    handler = ActivateOfferingHandler(offering_repository=repo)
    cmd = ActivateOffering(tenant_id=tid, business_id=bid, offering_id=oid)

    # --- Paso 1: llamar handler.handle() DIRECTAMENTE (sin execute_use_case)
    direct_result, direct_events = handler.handle(cmd)
    assert isinstance(direct_result, Offering)
    assert direct_result.status == CatalogItemStatus.ACTIVE
    # Los eventos se recolectan pero NO se publican fuera del execute_use_case
    assert any(isinstance(e, OfferingActivated) for e in direct_events)

    # --- Paso 2: ahora resetear y ejecutar por execute_use_case
    repo2 = FakeOfferingRepository()
    repo2.save(
        Offering(
            id=oid,
            tenant_id=tid,
            business_id=bid,
            name="Producto DRAFT 2",
            status=CatalogItemStatus.DRAFT,
        )
    )
    handler2 = ActivateOfferingHandler(offering_repository=repo2)
    uow = FakeUnitOfWork()
    disp = DomainEventDispatcher()
    pub = FakeEventPublisher()

    execute_use_case(
        handler=handler2,
        input=cmd,
        unit_of_work=uow,
        event_dispatcher=disp,
        event_publisher=pub,
    )

    assert uow.commit_count == 1
    assert len(pub.published) >= 1
    assert any(isinstance(e, OfferingActivated) for e in pub.published)


def test_deactivate_offering_happy() -> None:
    """Deactivate sobre ACTIVE → INACTIVE; OfferingDeactivated emitido."""
    tid = TenantId.generate()
    bid = BusinessId.generate()
    oid = OfferingId.generate()
    repo = FakeOfferingRepository()
    repo.save(
        Offering(
            id=oid,
            tenant_id=tid,
            business_id=bid,
            name="Activo",
            status=CatalogItemStatus.ACTIVE,
        )
    )
    handler = DeactivateOfferingHandler(offering_repository=repo)
    cmd = DeactivateOffering(tenant_id=tid, business_id=bid, offering_id=oid)

    uow = FakeUnitOfWork()
    disp = DomainEventDispatcher()
    pub = FakeEventPublisher()
    result = execute_use_case(
        handler=handler,
        input=cmd,
        unit_of_work=uow,
        event_dispatcher=disp,
        event_publisher=pub,
    )

    assert result.status == CatalogItemStatus.INACTIVE
    assert uow.commit_count == 1
    assert uow.rollback_count == 0
    assert len(pub.published) >= 1


def test_archive_offering_then_activate_handler_raises() -> None:
    """ARCHIVED no se puede re-activar (invariante de dominio)."""
    tid = TenantId.generate()
    bid = BusinessId.generate()
    oid = OfferingId.generate()
    repo = FakeOfferingRepository()

    archive_cmd = ArchiveOffering(tenant_id=tid, business_id=bid, offering_id=oid)
    activate_cmd = ActivateOffering(tenant_id=tid, business_id=bid, offering_id=oid)

    # Primero creamos un Offering DRAFT via repo.save directo
    repo.save(
        Offering(
            id=oid,
            tenant_id=tid,
            business_id=bid,
            name="Para archivar",
            status=CatalogItemStatus.DRAFT,
        )
    )

    # Archive → OK
    archive_handler = ArchiveOfferingHandler(offering_repository=repo)
    uow1 = FakeUnitOfWork()
    disp1 = DomainEventDispatcher()
    pub1 = FakeEventPublisher()
    archived = execute_use_case(
        handler=archive_handler,
        input=archive_cmd,
        unit_of_work=uow1,
        event_dispatcher=disp1,
        event_publisher=pub1,
    )
    assert archived.status == CatalogItemStatus.ARCHIVED
    assert uow1.commit_count == 1

    # Activate → falla con InvariantViolationError
    activate_handler = ActivateOfferingHandler(offering_repository=repo)
    uow2 = FakeUnitOfWork()
    disp2 = DomainEventDispatcher()
    pub2 = FakeEventPublisher()
    with pytest.raises(InvariantViolationError, match="No se puede activar"):
        execute_use_case(
            handler=activate_handler,
            input=activate_cmd,
            unit_of_work=uow2,
            event_dispatcher=disp2,
            event_publisher=pub2,
        )


# ============================================================================
# Tests ChangeOfferingPrice
# ============================================================================


def test_change_offering_price_happy() -> None:
    """Cambio de precio mismo currency: actualiza y emite OfferingPriceChanged."""
    tid = TenantId.generate()
    bid = BusinessId.generate()
    oid = OfferingId.generate()
    repo = FakeOfferingRepository()
    repo.save(
        Offering(
            id=oid,
            tenant_id=tid,
            business_id=bid,
            name="Pizza",
            status=CatalogItemStatus.ACTIVE,
            base_price=Money(Decimal("10.00"), "EUR"),
        )
    )

    handler = ChangeOfferingPriceHandler(offering_repository=repo)
    cmd = ChangeOfferingPrice(
        tenant_id=tid,
        business_id=bid,
        offering_id=oid,
        new_base_price_amount=Decimal("12.50"),
        new_currency="EUR",
    )

    uow = FakeUnitOfWork()
    disp = DomainEventDispatcher()
    pub = FakeEventPublisher()
    result = execute_use_case(
        handler=handler,
        input=cmd,
        unit_of_work=uow,
        event_dispatcher=disp,
        event_publisher=pub,
    )

    assert result.base_price == Money(Decimal("12.50"), "EUR")
    assert uow.commit_count == 1
    price_events = [e for e in pub.published if isinstance(e, OfferingPriceChanged)]
    assert len(price_events) == 1
    assert price_events[0].new_price_amount == Decimal("12.5000")
    assert price_events[0].currency == "EUR"


def test_change_offering_price_currency_mismatch_handler_raises() -> None:
    """Cambiar EUR → USD no permitido (currency mismatch del dominio)."""
    tid = TenantId.generate()
    bid = BusinessId.generate()
    oid = OfferingId.generate()
    repo = FakeOfferingRepository()
    repo.save(
        Offering(
            id=oid,
            tenant_id=tid,
            business_id=bid,
            name="Pizza EUR",
            status=CatalogItemStatus.ACTIVE,
            base_price=Money(Decimal("10.00"), "EUR"),
        )
    )

    handler = ChangeOfferingPriceHandler(offering_repository=repo)
    cmd = ChangeOfferingPrice(
        tenant_id=tid,
        business_id=bid,
        offering_id=oid,
        new_base_price_amount=Decimal("12.50"),
        new_currency="USD",
    )

    uow = FakeUnitOfWork()
    disp = DomainEventDispatcher()
    pub = FakeEventPublisher()
    with pytest.raises(MoneyCurrencyMismatchError):
        execute_use_case(
            handler=handler,
            input=cmd,
            unit_of_work=uow,
            event_dispatcher=disp,
            event_publisher=pub,
        )
    assert uow.commit_count == 0
    assert pub.published == []


# ============================================================================
# Tests CreateCatalogCategory
# ============================================================================


def test_create_category_happy() -> None:
    """Happy path: categoría creada y persistida, event emitido post-commit."""
    tid = TenantId.generate()
    bid = BusinessId.generate()
    cid = CatalogCategoryId.generate()

    repo = FakeCatalogCategoryRepository()
    store = FakeIdempotencyStore()
    uow = FakeUnitOfWork()
    disp = DomainEventDispatcher()
    pub = FakeEventPublisher()
    cat_handler = CreateCatalogCategoryHandler(
        category_repository=repo,
        idempotency_store=store,
    )
    cmd = CreateCatalogCategory(
        tenant_id=tid,
        business_id=bid,
        category_id=cid,
        name="Entradas",
        description="Platos fríos y calientes",
        idempotency_key=_new_idempotency_key("cat-happy-01"),
    )

    result = execute_use_case(
        handler=cat_handler,
        input=cmd,
        unit_of_work=uow,
        event_dispatcher=disp,
        event_publisher=pub,
    )

    assert isinstance(result, CatalogCategory)
    assert result.id == cid
    assert result.name == "Entradas"
    assert result.status == CatalogItemStatus.DRAFT
    assert uow.commit_count == 1

    entry = store.get(tid, cmd.idempotency_key)
    assert entry is not None
    assert entry[1] is result


def test_create_category_self_parent_handler_raises() -> None:
    """Category.id == parent_category_id → ApplicationError."""
    tid = TenantId.generate()
    bid = BusinessId.generate()
    cid = CatalogCategoryId.generate()

    repo = FakeCatalogCategoryRepository()
    store = FakeIdempotencyStore()
    cat_handler = CreateCatalogCategoryHandler(
        category_repository=repo,
        idempotency_store=store,
    )
    cmd = CreateCatalogCategory(
        tenant_id=tid,
        business_id=bid,
        category_id=cid,
        name="Soy mi propio padre",
        parent_category_id=cid,
        idempotency_key=_new_idempotency_key("cat-self-01"),
    )

    with pytest.raises(ApplicationError, match="propio padre"):
        cat_handler.handle(cmd)


# ============================================================================
# Tests Query handlers
# ============================================================================


def test_list_active_offerings_returns_only_active() -> None:
    """list_active filtra status ACTIVE y respeta location_id opcional."""
    tid = TenantId.generate()
    bid = BusinessId.generate()
    loc_a = LocationId.generate()
    loc_b = LocationId.generate()

    repo = FakeOfferingRepository()
    statuses = [
        CatalogItemStatus.ACTIVE,
        CatalogItemStatus.ACTIVE,
        CatalogItemStatus.INACTIVE,
        CatalogItemStatus.ARCHIVED,
        CatalogItemStatus.DRAFT,
    ]
    locations: list[frozenset[LocationId]] = [
        frozenset([loc_a]),
        frozenset([loc_b]),
        frozenset([loc_a]),
        frozenset([loc_a]),
        frozenset([loc_a, loc_b]),
    ]
    names = ["A1", "B1", "I1", "R1", "D1"]
    for i, (s, locs, n) in enumerate(zip(statuses, locations, names, strict=True)):
        repo.save(
            Offering(
                id=OfferingId.from_raw(int.to_bytes(1000 + i, 16, "big")),
                tenant_id=tid,
                business_id=bid,
                name=n,
                status=s,
                location_ids=locs,
            )
        )

    handler = ListActiveOfferingsHandler(offering_repository=repo)

    # Sin filtro de location → 2 ACTIVE (A1 + B1)
    q_all = ListActiveOfferings(tenant_id=tid, business_id=bid)
    result_all, _ = handler.handle(q_all)
    assert len(result_all) == 2
    names_all = {o.name for o in result_all}
    assert names_all == {"A1", "B1"}

    # Filtrado por loc_a → solo A1
    q_a = ListActiveOfferings(tenant_id=tid, business_id=bid, location_id=loc_a)
    result_a, _ = handler.handle(q_a)
    assert len(result_a) == 1
    assert result_a[0].name == "A1"

    # Filtrado por loc_b → solo B1
    q_b = ListActiveOfferings(tenant_id=tid, business_id=bid, location_id=loc_b)
    result_b, _ = handler.handle(q_b)
    assert len(result_b) == 1
    assert result_b[0].name == "B1"


def test_get_offering_not_found_returns_none() -> None:
    """GetOffering sobre id inexistente devuelve None + events vacíos."""
    tid = TenantId.generate()
    bid = BusinessId.generate()
    repo = FakeOfferingRepository()
    handler = GetOfferingHandler(offering_repository=repo)
    q = GetOffering(
        tenant_id=tid,
        business_id=bid,
        offering_id=OfferingId.generate(),
    )
    result, events = handler.handle(q)
    assert result is None
    assert events == []


# ============================================================================
# Tests Idempotencia adicional
# ============================================================================


def test_create_offering_idempotency_duplicate_key_after_complete_is_noop() -> None:
    """2ª llamada con la misma idempotency_key DONE → devuelve cached, no repite lógica."""
    tid = TenantId.generate()
    bid = BusinessId.generate()
    oid = OfferingId.generate()
    key = _new_idempotency_key("idemp-dup-key-01")

    repo = FakeOfferingRepository()
    store = FakeIdempotencyStore()
    disp = DomainEventDispatcher()
    pub = FakeEventPublisher()
    handler = CreateOfferingHandler(
        offering_repository=repo,
        idempotency_store=store,
    )
    cmd = _build_base_offering_command(
        tenant_id=tid,
        business_id=bid,
        offering_id=oid,
        idempotency_key=key,
    )

    # --- Primera llamada ---
    uow1 = FakeUnitOfWork()
    first = execute_use_case(
        handler=handler,
        input=cmd,
        unit_of_work=uow1,
        event_dispatcher=disp,
        event_publisher=pub,
    )
    assert uow1.commit_count == 1
    saves_after_first = len(repo.save_calls)

    # --- Segunda llamada con MISMA key ---
    uow2 = FakeUnitOfWork()
    pub2 = FakeEventPublisher()
    second = execute_use_case(
        handler=handler,
        input=cmd,
        unit_of_work=uow2,
        event_dispatcher=disp,
        event_publisher=pub2,
    )

    # El resultado es EL MISMO offering (devuelto por caché del store)
    assert second is first
    # Segundo execute NO hizo commit del handler (porque devolvió cached antes de uow)
    # Pero el handler lo manejó dentro de su propia lógica.
    # Además, NO hubo más save_calls (no re-ejecutó lógica de creación)
    assert len(repo.save_calls) == saves_after_first, (
        "Las llamadas idempotentes duplicadas no deben disparar save adicionales"
    )
