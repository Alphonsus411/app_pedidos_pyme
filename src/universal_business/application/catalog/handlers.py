"""Handlers concretos para Catalog Commands y Queries (Gate 0.3).

Cada handler implementa estructuralmente :class:`CommandHandler` /
:class:`QueryHandler` y :class:`UseCaseHandler`. El método ``handle`` devuelve
la tupla canónica ``(resultado, eventos)``. Los mutations hacen cross-tenant
check cuando aplican. Los creates con idempotencia usan
:class:`IdempotencyStore` (reserve / complete / release) VÍA EL NUEVO PATRÓN
STATLESS: ``build_hooks`` devuelve un :class:`ExecutionHooks` con closures
``on_success`` / ``on_failure`` que capturan el estado por-ejecución.
**NUNCA** se guarda estado mutable en ``self`` de la instancia handler.

**Regla importante**: ningún handler de este archivo llama a
``uow.commit()`` — el commit lo hace exclusivamente el helper
:func:`execute_use_case` de la capa de ejecución.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import TYPE_CHECKING

from universal_business.application.catalog.commands import (
    ActivateOffering,
    ArchiveOffering,
    ChangeOfferingPrice,
    CreateCatalogCategory,
    CreateOffering,
    DeactivateOffering,
)
from universal_business.application.catalog.queries import (
    GetOffering,
    ListActiveOfferings,
    ListCategoriesByBusiness,
    ListOfferingsByBusiness,
    ListOfferingsByLocation,
)
from universal_business.application.errors import ApplicationError, IdempotencyConflictError
from universal_business.application.execution import (
    ExecutionHooks,
    UseCaseHandlerWithExecutionHooks,
)
from universal_business.application.idempotency import IdempotencyKey, IdempotencyStore
from universal_business.domain.catalog.entities import CatalogCategory, Offering
from universal_business.domain.catalog.events import (
    CatalogCategoryCreated,
    OfferingCreated,
)
from universal_business.domain.catalog.ports import (
    ICatalogCategoryRepository,
    IOfferingRepository,
)
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import BusinessId, TenantId
from universal_business.domain.shared.value_objects.money import Money

if TYPE_CHECKING:
    pass


_CROSS_SCOPE_MSG = "cross-tenant/business mutation denied"


def _command_digest(command: object) -> str:
    """Helper simple para generar un request_digest de un command frozen."""
    raw = repr(command)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _result_digest(result: object) -> str:
    raw = str(id(result)) + repr(result)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _assert_same_scope(
    *,
    entity_tenant_id: TenantId,
    entity_business_id: BusinessId,
    command_tenant_id: TenantId,
    command_business_id: BusinessId,
    entity_label: str = "entity",
) -> None:
    """Cross-scope mutation guard (tenant + business isolation)."""
    if entity_tenant_id != command_tenant_id or entity_business_id != command_business_id:
        raise ApplicationError(
            f"Cross-scope mutation DENIED: {entity_label} pertenece a"
            f" tenant={entity_tenant_id} business={entity_business_id}"
            f" pero command usa tenant={command_tenant_id} business={command_business_id}."
        )


# ---------------------------------------------------------------------------
# Command handlers — Offering
# ---------------------------------------------------------------------------


class CreateOfferingHandler(UseCaseHandlerWithExecutionHooks[CreateOffering, Offering]):
    def __init__(
        self,
        *,
        offering_repository: IOfferingRepository,
        idempotency_store: IdempotencyStore,
    ) -> None:
        self._offering_repository = offering_repository
        self._idempotency_store = idempotency_store

    def handle(
        self,
        command: CreateOffering,
        /,
    ) -> tuple[Offering, Sequence[DomainEvent]]:
        id_key: IdempotencyKey | None = command.idempotency_key
        tid = command.tenant_id
        store = self._idempotency_store
        reserved_ok = False

        if id_key is not None:
            reserved = store.reserve(
                tid,
                id_key,
                _command_digest(command),
            )
            if not reserved:
                cached = store.get(tid, id_key)
                if cached is not None:
                    result_obj = cached[1]
                    if isinstance(result_obj, Offering):
                        return (result_obj, [])
                raise IdempotencyConflictError(f"Idempotency conflict for key {id_key.value}")
            reserved_ok = True

        try:
            if (command.base_price is None) != (command.currency is None):
                raise ApplicationError(
                    "base_price y currency deben estar ambos presentes o ambos None"
                )

            existing = self._offering_repository.get(
                tenant_id=tid,
                business_id=command.business_id,
                offering_id=command.offering_id,
            )
            if existing is not None:
                if id_key is not None:
                    _assert_same_scope(
                        entity_tenant_id=existing.tenant_id,
                        entity_business_id=existing.business_id,
                        command_tenant_id=tid,
                        command_business_id=command.business_id,
                        entity_label="Offering",
                    )
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
            return (offering, list(events))
        except BaseException:
            if reserved_ok and id_key is not None:
                try:
                    store.release(tid, id_key)
                except Exception:
                    pass
            raise

    def build_hooks(
        self,
        input: CreateOffering,
        result: Offering,
        /,
    ) -> ExecutionHooks[Offering] | None:
        id_key: IdempotencyKey | None = input.idempotency_key
        if id_key is None:
            return None
        store = self._idempotency_store
        tid = input.tenant_id
        key = id_key
        digest = _result_digest(result)
        result_obj = result

        def _on_success(_res: Offering, /) -> None:
            store.complete(tid, key, digest, result_obj)

        def _on_failure(_exc: BaseException, /) -> None:
            store.release(tid, key)

        return ExecutionHooks[Offering](
            on_success=_on_success,
            on_failure=_on_failure,
        )


class ActivateOfferingHandler:
    def __init__(self, *, offering_repository: IOfferingRepository) -> None:
        self._offering_repository = offering_repository

    def handle(
        self,
        command: ActivateOffering,
        /,
    ) -> tuple[Offering, Sequence[DomainEvent]]:
        offering = self._offering_repository.get(
            tenant_id=command.tenant_id,
            business_id=command.business_id,
            offering_id=command.offering_id,
        )
        if offering is None:
            raise ApplicationError(f"Offering {command.offering_id} not found")
        _assert_same_scope(
            entity_tenant_id=offering.tenant_id,
            entity_business_id=offering.business_id,
            command_tenant_id=command.tenant_id,
            command_business_id=command.business_id,
            entity_label="Offering",
        )
        offering.activate()
        self._offering_repository.save(offering)
        events = offering.domain_events
        offering.clear_domain_events()
        return (offering, list(events))


class DeactivateOfferingHandler:
    def __init__(self, *, offering_repository: IOfferingRepository) -> None:
        self._offering_repository = offering_repository

    def handle(
        self,
        command: DeactivateOffering,
        /,
    ) -> tuple[Offering, Sequence[DomainEvent]]:
        offering = self._offering_repository.get(
            tenant_id=command.tenant_id,
            business_id=command.business_id,
            offering_id=command.offering_id,
        )
        if offering is None:
            raise ApplicationError(f"Offering {command.offering_id} not found")
        _assert_same_scope(
            entity_tenant_id=offering.tenant_id,
            entity_business_id=offering.business_id,
            command_tenant_id=command.tenant_id,
            command_business_id=command.business_id,
            entity_label="Offering",
        )
        offering.deactivate()
        self._offering_repository.save(offering)
        events = offering.domain_events
        offering.clear_domain_events()
        return (offering, list(events))


class ArchiveOfferingHandler:
    def __init__(self, *, offering_repository: IOfferingRepository) -> None:
        self._offering_repository = offering_repository

    def handle(
        self,
        command: ArchiveOffering,
        /,
    ) -> tuple[Offering, Sequence[DomainEvent]]:
        offering = self._offering_repository.get(
            tenant_id=command.tenant_id,
            business_id=command.business_id,
            offering_id=command.offering_id,
        )
        if offering is None:
            raise ApplicationError(f"Offering {command.offering_id} not found")
        _assert_same_scope(
            entity_tenant_id=offering.tenant_id,
            entity_business_id=offering.business_id,
            command_tenant_id=command.tenant_id,
            command_business_id=command.business_id,
            entity_label="Offering",
        )
        offering.archive()
        self._offering_repository.save(offering)
        events = offering.domain_events
        offering.clear_domain_events()
        return (offering, list(events))


class ChangeOfferingPriceHandler:
    def __init__(self, *, offering_repository: IOfferingRepository) -> None:
        self._offering_repository = offering_repository

    def handle(
        self,
        command: ChangeOfferingPrice,
        /,
    ) -> tuple[Offering, Sequence[DomainEvent]]:
        offering = self._offering_repository.get(
            tenant_id=command.tenant_id,
            business_id=command.business_id,
            offering_id=command.offering_id,
        )
        if offering is None:
            raise ApplicationError(f"Offering {command.offering_id} not found")
        _assert_same_scope(
            entity_tenant_id=offering.tenant_id,
            entity_business_id=offering.business_id,
            command_tenant_id=command.tenant_id,
            command_business_id=command.business_id,
            entity_label="Offering",
        )
        new_price = Money(command.new_base_price_amount, command.new_currency)
        offering.change_base_price(new_price)
        self._offering_repository.save(offering)
        events = offering.domain_events
        offering.clear_domain_events()
        return (offering, list(events))


# ---------------------------------------------------------------------------
# Command handlers — CatalogCategory
# ---------------------------------------------------------------------------


class CreateCatalogCategoryHandler(
    UseCaseHandlerWithExecutionHooks[CreateCatalogCategory, CatalogCategory]
):
    def __init__(
        self,
        *,
        category_repository: ICatalogCategoryRepository,
        idempotency_store: IdempotencyStore,
    ) -> None:
        self._category_repository = category_repository
        self._idempotency_store = idempotency_store

    def handle(
        self,
        command: CreateCatalogCategory,
        /,
    ) -> tuple[CatalogCategory, Sequence[DomainEvent]]:
        id_key: IdempotencyKey | None = command.idempotency_key
        tid = command.tenant_id
        store = self._idempotency_store
        reserved_ok = False

        if id_key is not None:
            reserved = store.reserve(
                tid,
                id_key,
                _command_digest(command),
            )
            if not reserved:
                cached = store.get(tid, id_key)
                if cached is not None:
                    result_obj = cached[1]
                    if isinstance(result_obj, CatalogCategory):
                        return (result_obj, [])
                raise IdempotencyConflictError(f"Idempotency conflict for key {id_key.value}")
            reserved_ok = True

        try:
            if (
                command.parent_category_id is not None
                and command.category_id == command.parent_category_id
            ):
                raise ApplicationError("Category no puede ser su propio padre")

            existing = self._category_repository.get(
                tenant_id=tid,
                business_id=command.business_id,
                category_id=command.category_id,
            )
            if existing is not None:
                if id_key is not None:
                    _assert_same_scope(
                        entity_tenant_id=existing.tenant_id,
                        entity_business_id=existing.business_id,
                        command_tenant_id=tid,
                        command_business_id=command.business_id,
                        entity_label="CatalogCategory",
                    )
                    return (existing, [])
                raise ApplicationError(f"CatalogCategory {command.category_id} already exists")

            category = CatalogCategory(
                id=command.category_id,
                tenant_id=tid,
                business_id=command.business_id,
                name=command.name,
                description=command.description,
                parent_category_id=command.parent_category_id,
            )
            category.add_domain_event(
                CatalogCategoryCreated(
                    aggregate_id=category.id,
                    tenant_id=category.tenant_id,
                    business_id=category.business_id,
                )
            )
            self._category_repository.save(category)
            events = category.domain_events
            category.clear_domain_events()
            return (category, list(events))
        except BaseException:
            if reserved_ok and id_key is not None:
                try:
                    store.release(tid, id_key)
                except Exception:
                    pass
            raise

    def build_hooks(
        self,
        input: CreateCatalogCategory,
        result: CatalogCategory,
        /,
    ) -> ExecutionHooks[CatalogCategory] | None:
        id_key: IdempotencyKey | None = input.idempotency_key
        if id_key is None:
            return None
        store = self._idempotency_store
        tid = input.tenant_id
        key = id_key
        digest = _result_digest(result)
        result_obj = result

        def _on_success(_res: CatalogCategory, /) -> None:
            store.complete(tid, key, digest, result_obj)

        def _on_failure(_exc: BaseException, /) -> None:
            store.release(tid, key)

        return ExecutionHooks[CatalogCategory](
            on_success=_on_success,
            on_failure=_on_failure,
        )


# ---------------------------------------------------------------------------
# Query handlers
# ---------------------------------------------------------------------------


class GetOfferingHandler:
    def __init__(self, *, offering_repository: IOfferingRepository) -> None:
        self._offering_repository = offering_repository

    def handle(
        self,
        query: GetOffering,
        /,
    ) -> Offering | None:
        return self._offering_repository.get(
            tenant_id=query.tenant_id,
            business_id=query.business_id,
            offering_id=query.offering_id,
        )


class ListOfferingsByBusinessHandler:
    def __init__(self, *, offering_repository: IOfferingRepository) -> None:
        self._offering_repository = offering_repository

    def handle(
        self,
        query: ListOfferingsByBusiness,
        /,
    ) -> list[Offering]:
        result = self._offering_repository.list_by_business(
            tenant_id=query.tenant_id,
            business_id=query.business_id,
            location_id=query.location_id,
            status=query.status,
        )
        return list(result)


class ListOfferingsByLocationHandler:
    def __init__(self, *, offering_repository: IOfferingRepository) -> None:
        self._offering_repository = offering_repository

    def handle(
        self,
        query: ListOfferingsByLocation,
        /,
    ) -> list[Offering]:
        result = self._offering_repository.list_by_business(
            tenant_id=query.tenant_id,
            business_id=query.business_id,
            location_id=query.location_id,
        )
        return list(result)


class ListActiveOfferingsHandler:
    def __init__(self, *, offering_repository: IOfferingRepository) -> None:
        self._offering_repository = offering_repository

    def handle(
        self,
        query: ListActiveOfferings,
        /,
    ) -> list[Offering]:
        result = self._offering_repository.list_active(
            tenant_id=query.tenant_id,
            business_id=query.business_id,
            location_id=query.location_id,
        )
        return list(result)


class ListCategoriesByBusinessHandler:
    def __init__(self, *, category_repository: ICatalogCategoryRepository) -> None:
        self._category_repository = category_repository

    def handle(
        self,
        query: ListCategoriesByBusiness,
        /,
    ) -> list[CatalogCategory]:
        result = self._category_repository.list_by_business(
            tenant_id=query.tenant_id,
            business_id=query.business_id,
            status=query.status,
            parent_category_id=query.parent_category_id,
        )
        return list(result)


__all__ = [
    # Offering commands
    "CreateOfferingHandler",
    "ActivateOfferingHandler",
    "DeactivateOfferingHandler",
    "ArchiveOfferingHandler",
    "ChangeOfferingPriceHandler",
    # Category commands
    "CreateCatalogCategoryHandler",
    # Query handlers
    "GetOfferingHandler",
    "ListOfferingsByBusinessHandler",
    "ListOfferingsByLocationHandler",
    "ListActiveOfferingsHandler",
    "ListCategoriesByBusinessHandler",
]
