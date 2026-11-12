"""Contrato previo a las escrituras privadas de pedidos (F3.9).

No crea rutas HTTP ni ejecuta comandos. La frontera HTTP futura deberá
autenticar al actor, resolver el pedido dentro del ámbito de servidor y
verificar estos permisos ANTES de una posible respuesta idempotente.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from apps.api.app.staff_auth import StaffPrincipal, StaffRole

from universal_business.domain.orders.lifecycle import allowed_order_transitions
from universal_business.domain.orders.value_objects import OrderStatus


class OrderManagementAction(StrEnum):
    VALIDATE = "validate"
    CONFIRM = "confirm"
    RETURN_TO_DRAFT = "return_to_draft"
    CANCEL = "cancel"
    PREPARE = "prepare"
    MARK_READY = "mark_ready"
    DISPATCH = "dispatch"
    COMPLETE = "complete"


_ACTION_TARGETS: dict[OrderManagementAction, OrderStatus] = {
    OrderManagementAction.VALIDATE: OrderStatus.VALIDATED,
    OrderManagementAction.CONFIRM: OrderStatus.CONFIRMED,
    OrderManagementAction.RETURN_TO_DRAFT: OrderStatus.DRAFT,
    OrderManagementAction.CANCEL: OrderStatus.CANCELLED,
    OrderManagementAction.PREPARE: OrderStatus.PREPARING,
    OrderManagementAction.MARK_READY: OrderStatus.READY,
    OrderManagementAction.DISPATCH: OrderStatus.DELIVERING,
    OrderManagementAction.COMPLETE: OrderStatus.COMPLETED,
}


class ManagementScopeNotFound(ValueError):
    """Ámbito no publicado: no revelar si el pedido existe."""


class ManagementForbidden(ValueError):
    """La identidad autenticada no dispone de manage_orders."""


class ManagementTransitionRejected(ValueError):
    """La transición no está permitida por la matriz de dominio."""


@dataclass(frozen=True, slots=True)
class AuthorizedOrderTransition:
    business_slug: str
    location_slug: str
    action: OrderManagementAction
    target: OrderStatus


def authorize_order_transition(
    *,
    principal: StaffPrincipal,
    business_slug: str,
    location_slug: str,
    published_scopes: frozenset[tuple[str, str]],
    action: OrderManagementAction,
    current_status: OrderStatus,
) -> AuthorizedOrderTransition:
    """Prevalidación para el futuro adaptador HTTP; nunca persiste estados.

    Orden estricto: ámbito publicado -> grant de escritura -> matriz de dominio.
    No acepta tenant_id, business_id ni grants proporcionados por HTTP.
    La API deberá volver a comprobar el alcance del pedido y ejecutar la
    política del caso de uso, la UoW y la idempotencia en el servidor.
    """
    if (business_slug, location_slug) not in published_scopes:
        raise ManagementScopeNotFound
    if not principal.allows(
        business_slug=business_slug,
        location_slug=location_slug,
        role=StaffRole.MANAGE_ORDERS,
    ):
        raise ManagementForbidden
    if not isinstance(action, OrderManagementAction) or not isinstance(
        current_status, OrderStatus
    ):
        raise ManagementTransitionRejected
    target = _ACTION_TARGETS[action]
    if target not in allowed_order_transitions(current_status):
        raise ManagementTransitionRejected
    return AuthorizedOrderTransition(
        business_slug=business_slug,
        location_slug=location_slug,
        action=action,
        target=target,
    )
