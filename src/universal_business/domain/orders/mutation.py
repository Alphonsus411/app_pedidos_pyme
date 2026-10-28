"""Contrato transaccional para mutaciones concurrentes de pedidos."""

from __future__ import annotations

from typing import Protocol

from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    OrderId,
    TenantId,
)


class OrderMutationGuard(Protocol):
    """Proteger el pedido hasta el fin de la misma UnitOfWork.

    El guard y el repositorio deben compartir la misma transacción. Todas las
    mutaciones del mismo pedido deben usar protección compatible o aislamiento
    equivalente, incluida la edición de líneas y el cambio de estado. El caller
    debe releer bajo protección, comprobar tenant/business/location e invariantes
    y persistir antes de commit. El guard no crea pedidos, ni confirma, ni hace
    commit, ni valida permisos. La unicidad de creación requiere un mecanismo
    transaccional separado.

    Al devolver, la protección debe mantenerse hasta commit o rollback. Un
    commit incierto requiere reconciliación, no presupone rollback efectivo.
    El adaptador debe rechazar ámbito incorrecto y gestionar fallos y deadlocks;
    no debe revelar información de otro ámbito.
    """

    def protect(
        self,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId,
        order_id: OrderId,
    ) -> None:
        """Proteger la identidad y el ámbito hasta el fin de la transacción."""
        ...


__all__ = ["OrderMutationGuard"]
