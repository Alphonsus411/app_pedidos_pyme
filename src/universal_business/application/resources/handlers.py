"""Handlers concretos (Command + Query) para el módulo Resources (Gate 0.3).

Reglas implementadas (no negociables):
- Los handlers de Command devuelven ``tuple(result, list[DomainEvent])``.
- Los handlers de Query devuelven el resultado directamente (no events).
- **Ningún handler llama a ``uow.commit()``**: ese paso le corresponde a
  :func:`execute_use_case` (o al orquestador superior). El handler solo hace
  orquestación + invocación de métodos de dominio + save() en repos.
- Cross-scope mutation DENIED (tenant + business): se levanta
  :class:`ApplicationError`.
- Idempotencia: flujo ``reserve`` en handle(), ``complete`` en
  ``post_commit_success`` y ``release`` en ``post_rollback`` usando
  :class:`IdempotencyStore`.
"""

from __future__ import annotations

from dataclasses import asdict

from universal_business.application.errors import ApplicationError
from universal_business.application.idempotency import (
    IdempotencyKey,
    IdempotencyStore,
)
from universal_business.application.messaging.handlers import (
    CommandHandler,
    QueryHandler,
)
from universal_business.application.resources.commands import (
    ActivateResource,
    ArchiveResource,
    AssignResourceToLocation,
    CreateResource,
    CreateResourceType,
    DeactivateResource,
)
from universal_business.application.resources.queries import (
    GetResource,
    ListActiveResources,
    ListResourceTypesByBusiness,
    ListResourcesByBusiness,
    ListResourcesByLocation,
)
from universal_business.domain.resources.entities import (
    Resource,
)
from universal_business.domain.resources.entities import (
    ResourceType as ResourceTypeEntity,
)
from universal_business.domain.resources.ports import (
    IResourceRepository,
    IResourceTypeRepository,
)
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    TenantId,
)

# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _command_digest(command: object) -> str:
    """Genera un digest determinista (simple) para una request idempotente.

    En producción el adapter real usaría hash criptográfico; aquí basta con
    una representación textual estable (suficiente para tests y semántica).
    """
    try:
        data = asdict(command)  # type: ignore[call-overload]
    except Exception:  # noqa: BLE001 - fallback por seguridad
        data = {"cmd": type(command).__name__}
    data.pop("idempotency_key", None)
    return f"{type(command).__name__}:{sorted(data.items())!r}"


def _result_digest(result: object) -> str:
    """Digest simple para results almacenados en IdempotencyStore."""
    if result is None:
        return "None"
    if hasattr(result, "id"):
        return f"{type(result).__name__}:{result.id}"
    return f"{type(result).__name__}:{result!r}"


def _assert_same_scope(
    *,
    entity_tenant_id: TenantId,
    entity_business_id: BusinessId,
    command_tenant_id: TenantId,
    command_business_id: BusinessId,
    entity_label: str = "entity",
) -> None:
    """Cross-scope mutation guard (tenant + business isolation, AT-9)."""
    if entity_tenant_id != command_tenant_id or entity_business_id != command_business_id:
        raise ApplicationError(
            f"Cross-tenant mutation DENIED: {entity_label} pertenece a"
            f" tenant={entity_tenant_id} business={entity_business_id}"
            f" pero command usa tenant={command_tenant_id} business={command_business_id}."
        )


# ---------------------------------------------------------------------------
# Command Handlers
# ---------------------------------------------------------------------------


class CreateResourceTypeHandler(
    CommandHandler[CreateResourceType, tuple[ResourceTypeEntity, list[DomainEvent]]]
):
    """Crea un nuevo ResourceType con idempotencia opcional."""

    def __init__(
        self,
        *,
        resource_type_repo: IResourceTypeRepository,
        idempotency_store: IdempotencyStore | None = None,
    ) -> None:
        self.resource_type_repo = resource_type_repo
        self.idempotency_store = idempotency_store
        self._idem_pending: (
            tuple[
                IdempotencyStore,
                TenantId,
                IdempotencyKey,
                str,
                ResourceTypeEntity,
            ]
            | None
        ) = None

    def handle(
        self,
        command: CreateResourceType,
    ) -> tuple[ResourceTypeEntity, list[DomainEvent]]:
        key = command.idempotency_key
        store = self.idempotency_store
        tid = command.tenant_id

        if key is not None and store is not None:
            req_digest = _command_digest(command)
            if not store.reserve(tid, key, req_digest):
                cached = store.get(tid, key)
                if cached is not None:
                    cached_result = cached[1]
                    if isinstance(cached_result, ResourceTypeEntity):
                        return (cached_result, [])
                raise ApplicationError(f"Idempotency key {key} ya está RESERVED por otro worker.")
            self._idem_pending = (store, tid, key, "", None)  # type: ignore[assignment]

        rt = ResourceTypeEntity(
            id=command.resource_type_id,
            tenant_id=tid,
            business_id=command.business_id,
            name=command.name,
            description=command.description,
        )
        events = list(rt.domain_events)
        self.resource_type_repo.save(rt)

        if key is not None and store is not None:
            self._idem_pending = (store, tid, key, _result_digest(rt), rt)

        return (rt, events)

    def post_commit_success(self, result: ResourceTypeEntity, /) -> None:
        if self._idem_pending is None:
            return
        (store, tid, key, digest, _res_captured) = self._idem_pending
        self._idem_pending = None
        store.complete(tid, key, digest, _res_captured)

    def post_rollback(self, exc: BaseException, /) -> None:
        if self._idem_pending is None:
            return
        (store, tid, key, _digest, _res) = self._idem_pending
        self._idem_pending = None
        store.release(tid, key)


class CreateResourceHandler(CommandHandler[CreateResource, tuple[Resource, list[DomainEvent]]]):
    """Crea un nuevo Resource con strong validation de resource_type."""

    def __init__(
        self,
        *,
        resource_repo: IResourceRepository,
        resource_type_repo: IResourceTypeRepository,
        idempotency_store: IdempotencyStore | None = None,
    ) -> None:
        self.resource_repo = resource_repo
        self.resource_type_repo = resource_type_repo
        self.idempotency_store = idempotency_store
        self._idem_pending: (
            tuple[IdempotencyStore, TenantId, IdempotencyKey, str, Resource] | None
        ) = None

    def handle(self, command: CreateResource) -> tuple[Resource, list[DomainEvent]]:
        key = command.idempotency_key
        store = self.idempotency_store
        tid = command.tenant_id

        if key is not None and store is not None:
            req_digest = _command_digest(command)
            if not store.reserve(tid, key, req_digest):
                cached = store.get(tid, key)
                if cached is not None:
                    cached_result = cached[1]
                    if isinstance(cached_result, Resource):
                        return (cached_result, [])
                raise ApplicationError(f"Idempotency key {key} ya está RESERVED por otro worker.")
            self._idem_pending = (store, tid, key, "", None)  # type: ignore[assignment]

        rt = self.resource_type_repo.get(
            tenant_id=tid,
            business_id=command.business_id,
            resource_type_id=command.resource_type_id,
        )
        if rt is None:
            raise ApplicationError(
                f"ResourceType {command.resource_type_id} not found for tenant/business"
            )
        _assert_same_scope(
            entity_tenant_id=rt.tenant_id,
            entity_business_id=rt.business_id,
            command_tenant_id=tid,
            command_business_id=command.business_id,
            entity_label="ResourceType",
        )

        r = Resource(
            id=command.resource_id,
            tenant_id=tid,
            business_id=command.business_id,
            resource_type_id=command.resource_type_id,
            name=command.name,
            location_id=command.location_id,
            capacity=command.capacity if command.capacity > 0 else None,
        )
        events = list(r.domain_events)
        self.resource_repo.save(r)

        if key is not None and store is not None:
            self._idem_pending = (store, tid, key, _result_digest(r), r)

        return (r, events)

    def post_commit_success(self, result: Resource, /) -> None:
        if self._idem_pending is None:
            return
        (store, tid, key, digest, _res_captured) = self._idem_pending
        self._idem_pending = None
        store.complete(tid, key, digest, _res_captured)

    def post_rollback(self, exc: BaseException, /) -> None:
        if self._idem_pending is None:
            return
        (store, tid, key, _digest, _res) = self._idem_pending
        self._idem_pending = None
        store.release(tid, key)


class ActivateResourceHandler(CommandHandler[ActivateResource, tuple[Resource, list[DomainEvent]]]):
    def __init__(self, *, resource_repo: IResourceRepository) -> None:
        self.resource_repo = resource_repo

    def handle(self, command: ActivateResource) -> tuple[Resource, list[DomainEvent]]:
        r = self.resource_repo.get(
            tenant_id=command.tenant_id,
            business_id=command.business_id,
            resource_id=command.resource_id,
        )
        if r is None:
            raise ApplicationError(f"Resource {command.resource_id} not found")
        _assert_same_scope(
            entity_tenant_id=r.tenant_id,
            entity_business_id=r.business_id,
            command_tenant_id=command.tenant_id,
            command_business_id=command.business_id,
            entity_label="Resource",
        )
        r.clear_domain_events()
        r.activate()
        events = list(r.domain_events)
        self.resource_repo.save(r)
        return (r, events)


class DeactivateResourceHandler(
    CommandHandler[DeactivateResource, tuple[Resource, list[DomainEvent]]]
):
    def __init__(self, *, resource_repo: IResourceRepository) -> None:
        self.resource_repo = resource_repo

    def handle(self, command: DeactivateResource) -> tuple[Resource, list[DomainEvent]]:
        r = self.resource_repo.get(
            tenant_id=command.tenant_id,
            business_id=command.business_id,
            resource_id=command.resource_id,
        )
        if r is None:
            raise ApplicationError(f"Resource {command.resource_id} not found")
        _assert_same_scope(
            entity_tenant_id=r.tenant_id,
            entity_business_id=r.business_id,
            command_tenant_id=command.tenant_id,
            command_business_id=command.business_id,
            entity_label="Resource",
        )
        r.clear_domain_events()
        r.deactivate()
        events = list(r.domain_events)
        self.resource_repo.save(r)
        return (r, events)


class ArchiveResourceHandler(CommandHandler[ArchiveResource, tuple[Resource, list[DomainEvent]]]):
    def __init__(self, *, resource_repo: IResourceRepository) -> None:
        self.resource_repo = resource_repo

    def handle(self, command: ArchiveResource) -> tuple[Resource, list[DomainEvent]]:
        r = self.resource_repo.get(
            tenant_id=command.tenant_id,
            business_id=command.business_id,
            resource_id=command.resource_id,
        )
        if r is None:
            raise ApplicationError(f"Resource {command.resource_id} not found")
        _assert_same_scope(
            entity_tenant_id=r.tenant_id,
            entity_business_id=r.business_id,
            command_tenant_id=command.tenant_id,
            command_business_id=command.business_id,
            entity_label="Resource",
        )
        r.clear_domain_events()
        r.archive()
        events = list(r.domain_events)
        self.resource_repo.save(r)
        return (r, events)


class AssignResourceToLocationHandler(
    CommandHandler[AssignResourceToLocation, tuple[Resource, list[DomainEvent]]]
):
    def __init__(self, *, resource_repo: IResourceRepository) -> None:
        self.resource_repo = resource_repo

    def handle(self, command: AssignResourceToLocation) -> tuple[Resource, list[DomainEvent]]:
        r = self.resource_repo.get(
            tenant_id=command.tenant_id,
            business_id=command.business_id,
            resource_id=command.resource_id,
        )
        if r is None:
            raise ApplicationError(f"Resource {command.resource_id} not found")
        _assert_same_scope(
            entity_tenant_id=r.tenant_id,
            entity_business_id=r.business_id,
            command_tenant_id=command.tenant_id,
            command_business_id=command.business_id,
            entity_label="Resource",
        )
        r.clear_domain_events()
        r.assign_to_location(command.new_location_id)
        events = list(r.domain_events)
        self.resource_repo.save(r)
        return (r, events)


# ---------------------------------------------------------------------------
# Query Handlers
# ---------------------------------------------------------------------------


class GetResourceHandler(QueryHandler[GetResource, Resource | None]):
    def __init__(self, *, resource_repo: IResourceRepository) -> None:
        self.resource_repo = resource_repo

    def handle(self, query: GetResource) -> Resource | None:
        return self.resource_repo.get(
            tenant_id=query.tenant_id,
            business_id=query.business_id,
            resource_id=query.resource_id,
        )


class ListResourcesByBusinessHandler(QueryHandler[ListResourcesByBusiness, list[Resource]]):
    def __init__(self, *, resource_repo: IResourceRepository) -> None:
        self.resource_repo = resource_repo

    def handle(self, query: ListResourcesByBusiness) -> list[Resource]:
        return self.resource_repo.list_by_business(
            tenant_id=query.tenant_id,
            business_id=query.business_id,
            location_id=query.location_id,
            status=query.status,
            resource_type_id=query.resource_type_id,
        )


class ListResourcesByLocationHandler(QueryHandler[ListResourcesByLocation, list[Resource]]):
    def __init__(self, *, resource_repo: IResourceRepository) -> None:
        self.resource_repo = resource_repo

    def handle(self, query: ListResourcesByLocation) -> list[Resource]:
        return self.resource_repo.list_by_location(
            tenant_id=query.tenant_id,
            business_id=query.business_id,
            location_id=query.location_id,
            resource_type_id=query.resource_type_id,
        )


class ListActiveResourcesHandler(QueryHandler[ListActiveResources, list[Resource]]):
    def __init__(self, *, resource_repo: IResourceRepository) -> None:
        self.resource_repo = resource_repo

    def handle(self, query: ListActiveResources) -> list[Resource]:
        return self.resource_repo.list_active(
            tenant_id=query.tenant_id,
            business_id=query.business_id,
            location_id=query.location_id,
            resource_type_id=query.resource_type_id,
        )


class ListResourceTypesByBusinessHandler(
    QueryHandler[ListResourceTypesByBusiness, list[ResourceTypeEntity]]
):
    def __init__(self, *, resource_type_repo: IResourceTypeRepository) -> None:
        self.resource_type_repo = resource_type_repo

    def handle(self, query: ListResourceTypesByBusiness) -> list[ResourceTypeEntity]:
        return self.resource_type_repo.list_by_business(
            tenant_id=query.tenant_id,
            business_id=query.business_id,
            status=query.status,
        )


__all__ = [
    # Commands
    "CreateResourceTypeHandler",
    "CreateResourceHandler",
    "ActivateResourceHandler",
    "DeactivateResourceHandler",
    "ArchiveResourceHandler",
    "AssignResourceToLocationHandler",
    # Queries
    "GetResourceHandler",
    "ListResourcesByBusinessHandler",
    "ListResourcesByLocationHandler",
    "ListActiveResourcesHandler",
    "ListResourceTypesByBusinessHandler",
]
