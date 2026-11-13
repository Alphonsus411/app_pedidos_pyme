"""Transiciones de pedidos de personal, exclusivamente para laboratorio SQLite.

La sesión y CSRF se verifican en el borde HTTP; este adaptador revalida
permiso, ámbito y pedido antes de ejecutar el caso de uso transaccional.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from contextlib import closing

from apps.api.app.public_catalog import PublicCatalogScope
from apps.api.app.staff_auth import StaffPrincipal, StaffRole
from apps.api.app.staff_order_management import (
    _ACTION_TARGETS,
    ManagementForbidden,
    ManagementScopeNotFound,
    ManagementTransitionRejected,
    OrderManagementAction,
    authorize_order_transition,
)

from universal_business.application.errors import ApplicationError, IdempotencyConflictError
from universal_business.application.events.dispatcher import DomainEventDispatcher
from universal_business.application.idempotency import IdempotencyKey
from universal_business.application.orders.commands import (
    CancelOrder,
    CompleteOrder,
    ConfirmOrder,
    DispatchOrder,
    MarkOrderReady,
    OrderStatusCommand,
    PrepareOrder,
    ReturnOrderToDraft,
    ValidateOrder,
)
from universal_business.application.orders.status_change import OrderTransitionPolicy
from universal_business.domain.shared.errors import InvariantViolationError, StatusTransitionError
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import OrderId
from universal_business.infrastructure.sqlite_order_execution import SqliteOrderExecution
from universal_business.infrastructure.sqlite_orders import SqliteOrderRepository
from universal_business.infrastructure.sqlite_schema import initialize_sqlite_schema


class StaffTransitionNotFound(ValueError):
    """Pedido desconocido o perteneciente a otro ámbito."""


class StaffTransitionConflict(ValueError):
    """Transición/política/idempotencia incompatible con la solicitud."""


class StaffTransitionBusy(RuntimeError):
    """SQLite no pudo adquirir el bloqueo antes del timeout de laboratorio."""


class _OutboxOnlyPublisher:
    def publish(self, event: DomainEvent, /) -> None:
        del event

    def publish_many(self, events: Iterable[DomainEvent], /) -> None:
        del events


_COMMANDS: dict[OrderManagementAction, type[OrderStatusCommand]] = {
    OrderManagementAction.VALIDATE: ValidateOrder,
    OrderManagementAction.CONFIRM: ConfirmOrder,
    OrderManagementAction.RETURN_TO_DRAFT: ReturnOrderToDraft,
    OrderManagementAction.CANCEL: CancelOrder,
    OrderManagementAction.PREPARE: PrepareOrder,
    OrderManagementAction.MARK_READY: MarkOrderReady,
    OrderManagementAction.DISPATCH: DispatchOrder,
    OrderManagementAction.COMPLETE: CompleteOrder,
}


class SqliteStaffOrderTransitions:
    """Composición explícita para pruebas; no se activa por defecto."""

    def __init__(
        self,
        *,
        connect: Callable[[], sqlite3.Connection],
        scopes: dict[tuple[str, str], PublicCatalogScope],
        policy: OrderTransitionPolicy,
    ) -> None:
        self._connect = connect
        self._scopes = dict(scopes)
        self._policy = policy

    def change_status(
        self,
        *,
        principal: StaffPrincipal,
        business_slug: str,
        location_slug: str,
        order_id: str,
        action: OrderManagementAction,
        idempotency_key: str,
    ) -> dict[str, str]:
        scope = self._scopes.get((business_slug, location_slug))
        if scope is None:
            raise ManagementScopeNotFound
        if not principal.allows(
            business_slug=business_slug,
            location_slug=location_slug,
            role=StaffRole.MANAGE_ORDERS,
        ):
            raise ManagementForbidden
        try:
            parsed_order_id = OrderId.from_raw(order_id)
        except (ValueError, InvariantViolationError) as exc:
            raise StaffTransitionNotFound from exc
        try:
            key = IdempotencyKey(value=idempotency_key)
        except ValueError as exc:
            raise StaffTransitionConflict from exc

        try:
            with closing(self._connect()) as connection:
                initialize_sqlite_schema(connection)
                order = SqliteOrderRepository(connection).get(
                    tenant_id=scope.tenant_id, order_id=parsed_order_id
                )
                if order is None or (
                    order.business_id,
                    order.location_id,
                ) != (scope.business_id, scope.location_id):
                    raise StaffTransitionNotFound
                # Si el estado ya coincide, solo el caso de uso podrá acreditar un
                # replay con exactamente la misma clave y digest.
                if action not in _COMMANDS:
                    raise StaffTransitionConflict
                from_status = order.status
                target = _ACTION_TARGETS[action]
                if from_status != target:
                    try:
                        authorize_order_transition(
                            principal=principal,
                            business_slug=business_slug,
                            location_slug=location_slug,
                            published_scopes=frozenset(self._scopes),
                            action=action,
                            current_status=from_status,
                        )
                    except (ManagementTransitionRejected, ManagementForbidden) as exc:
                        raise StaffTransitionConflict from exc
                command = _COMMANDS[action](
                    tenant_id=scope.tenant_id,
                    business_id=scope.business_id,
                    location_id=scope.location_id,
                    order_id=parsed_order_id,
                    idempotency_key=key,
                )
                execution = SqliteOrderExecution(
                    connection,
                    dispatcher=DomainEventDispatcher(),
                    publisher=_OutboxOnlyPublisher(),
                    transition_policy=self._policy,
                )
                try:
                    result = execution.change_status(command)
                except (
                    ApplicationError,
                    IdempotencyConflictError,
                    InvariantViolationError,
                    StatusTransitionError,
                    ValueError,
                ) as exc:
                    raise StaffTransitionConflict from exc
                # La consulta del resultado confirma el destino de una ejecución
                # nueva o replay. Nunca se devuelve un resultado de otro ámbito.
                if (
                    result.order_id != parsed_order_id
                    or result.business_id != scope.business_id
                    or result.location_id != scope.location_id
                    or result.status != target
                ):
                    raise StaffTransitionConflict
                return {"id": str(result.order_id), "status": result.status.value}
        except sqlite3.OperationalError as exc:
            # Solo los códigos SQLite de contención son transitorios. Nunca
            # clasificar corrupción/esquemas inexistentes como reintentables.
            code = getattr(exc, "sqlite_errorcode", None)
            if code is not None and (code & 0xFF) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise StaffTransitionBusy from exc
            raise
