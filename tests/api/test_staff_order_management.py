"""F3.9: contrato negativo antes de habilitar administración de pedidos."""

from __future__ import annotations

import pytest
from apps.api.app.staff_auth import StaffGrant, StaffPrincipal, StaffRole
from apps.api.app.staff_order_management import (
    ManagementForbidden,
    ManagementScopeNotFound,
    ManagementTransitionRejected,
    OrderManagementAction,
    authorize_order_transition,
)

from universal_business.domain.orders.lifecycle import allowed_order_transitions
from universal_business.domain.orders.value_objects import OrderStatus


def _principal(*, role: StaffRole, business: str = "first", location: str = "main") -> StaffPrincipal:
    return StaffPrincipal(
        subject="synthetic-operator",
        grants=(StaffGrant(business, location, frozenset({role})),),
    )


def test_manage_orders_role_is_distinct_from_read_orders() -> None:
    reader = _principal(role=StaffRole.READ_ORDERS)
    assert reader.allows(
        business_slug="first", location_slug="main", role=StaffRole.READ_ORDERS
    )
    assert not reader.allows(
        business_slug="first", location_slug="main", role=StaffRole.MANAGE_ORDERS
    )
    writer = _principal(role=StaffRole.MANAGE_ORDERS)
    assert writer.allows(
        business_slug="first", location_slug="main", role=StaffRole.MANAGE_ORDERS
    )
    assert not writer.allows(
        business_slug="first", location_slug="main", role=StaffRole.READ_ORDERS
    )


def test_management_requires_explicit_grant_before_any_transition() -> None:
    with pytest.raises(ManagementForbidden):
        authorize_order_transition(
            principal=_principal(role=StaffRole.READ_ORDERS),
            business_slug="first",
            location_slug="main",
            published_scopes=frozenset({("first", "main")}),
            action=OrderManagementAction.VALIDATE,
            current_status=OrderStatus.DRAFT,
        )


@pytest.mark.parametrize(
    ("business", "location"),
    [("second", "main"), ("first", "branch"), ("unknown", "main")],
)
def test_management_cannot_cross_business_or_location(business: str, location: str) -> None:
    with pytest.raises(ManagementForbidden):
        authorize_order_transition(
            principal=_principal(role=StaffRole.MANAGE_ORDERS),
            business_slug=business,
            location_slug=location,
            published_scopes=frozenset(
                {("first", "main"), ("second", "main"), ("first", "branch"), ("unknown", "main")}
            ),
            action=OrderManagementAction.VALIDATE,
            current_status=OrderStatus.DRAFT,
        )


def test_unpublished_scope_fails_closed_even_for_powerful_grant() -> None:
    with pytest.raises(ManagementScopeNotFound):
        authorize_order_transition(
            principal=_principal(role=StaffRole.MANAGE_ORDERS),
            business_slug="first",
            location_slug="main",
            published_scopes=frozenset(),
            action=OrderManagementAction.VALIDATE,
            current_status=OrderStatus.DRAFT,
        )


@pytest.mark.parametrize(
    ("action", "source", "target"),
    [
        (OrderManagementAction.VALIDATE, OrderStatus.DRAFT, OrderStatus.VALIDATED),
        (OrderManagementAction.CONFIRM, OrderStatus.VALIDATED, OrderStatus.CONFIRMED),
        (OrderManagementAction.RETURN_TO_DRAFT, OrderStatus.VALIDATED, OrderStatus.DRAFT),
        (OrderManagementAction.CANCEL, OrderStatus.CONFIRMED, OrderStatus.CANCELLED),
        (OrderManagementAction.PREPARE, OrderStatus.CONFIRMED, OrderStatus.PREPARING),
        (OrderManagementAction.MARK_READY, OrderStatus.PREPARING, OrderStatus.READY),
        (OrderManagementAction.DISPATCH, OrderStatus.READY, OrderStatus.DELIVERING),
        (OrderManagementAction.COMPLETE, OrderStatus.DELIVERING, OrderStatus.COMPLETED),
    ],
)
def test_contract_matches_existing_domain_transitions(
    action: OrderManagementAction, source: OrderStatus, target: OrderStatus
) -> None:
    assert target in allowed_order_transitions(source)
    result = authorize_order_transition(
        principal=_principal(role=StaffRole.MANAGE_ORDERS),
        business_slug="first",
        location_slug="main",
        published_scopes=frozenset({("first", "main")}),
        action=action,
        current_status=source,
    )
    assert result.action is action
    assert result.target is target
    assert result.business_slug == "first"
    assert result.location_slug == "main"


@pytest.mark.parametrize(
    ("action", "source"),
    [
        (OrderManagementAction.CONFIRM, OrderStatus.DRAFT),
        (OrderManagementAction.PREPARE, OrderStatus.DRAFT),
        (OrderManagementAction.VALIDATE, OrderStatus.VALIDATED),
        (OrderManagementAction.CANCEL, OrderStatus.COMPLETED),
        (OrderManagementAction.COMPLETE, OrderStatus.CANCELLED),
    ],
)
def test_invalid_or_repeated_transitions_are_denied(
    action: OrderManagementAction, source: OrderStatus
) -> None:
    with pytest.raises(ManagementTransitionRejected):
        authorize_order_transition(
            principal=_principal(role=StaffRole.MANAGE_ORDERS),
            business_slug="first",
            location_slug="main",
            published_scopes=frozenset({("first", "main")}),
            action=action,
            current_status=source,
        )


def test_untrusted_action_type_cannot_bypass_transition_map() -> None:
    with pytest.raises(ManagementTransitionRejected):
        authorize_order_transition(
            principal=_principal(role=StaffRole.MANAGE_ORDERS),
            business_slug="first",
            location_slug="main",
            published_scopes=frozenset({("first", "main")}),
            action="confirm",  # type: ignore[arg-type]
            current_status=OrderStatus.VALIDATED,
        )
