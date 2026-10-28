"""Contrato de adjudicación transaccional para futuras confirmaciones."""

from __future__ import annotations

from typing import Protocol

from universal_business.domain.reservations.interval import ReservationInterval
from universal_business.domain.shared.errors import DomainError
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    ReservationId,
    ResourceId,
    TenantId,
)


class ReservationUnavailableError(DomainError):
    """La adjudicación no puede satisfacer la solicitud en su estado actual."""


class ReservationAllocationPort(Protocol):
    """Adquirir protección y verificar disponibilidad dentro de la transacción.

    El adaptador y el repositorio de reservas deben participar en la MISMA
    UnitOfWork. Una llamada exitosa protege el ámbito y recurso hasta que la
    transacción haga commit o rollback; no realiza commit, no devuelve un
    permiso duradero y no sustituye la persistencia de la reserva confirmada.
    El caller debe confirmar y guardar la reserva en esa misma transacción.

    Bajo dicha protección el adaptador debe verificar tenant, negocio,
    ubicación, recurso y estado, capacidad, ventanas, bloqueos y reservas
    ocupantes con semántica semiabierta. Las escrituras concurrentes que
    alteren esas condiciones, incluido cualquier cambio de estado, recurso,
    intervalo o cliente de la reserva solicitada, deben usar protección
    compatible o aislamiento equivalente hasta commit; de otro modo este
    contrato no se cumple. El recurso sin
    ubicación asignada debe rechazarse hasta que exista otra política.

    Fallo de disponibilidad produce ReservationUnavailableError; errores de
    almacenamiento se propagan. Un commit de resultado incierto requiere
    reconciliación conforme al contrato UnitOfWork e idempotencia; no debe
    asumirse que el rollback posterior deshizo un commit ya aplicado.
    La consulta informativa de disponibilidad no satisface este contrato.
    """

    def protect_and_check(
        self,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId,
        resource_id: ResourceId,
        reservation_id: ReservationId,
        interval: ReservationInterval,
        party_size: int | None,
    ) -> None:
        """Comprobar bajo protección retenida hasta el fin de la transacción."""
        ...


__all__ = ["ReservationAllocationPort", "ReservationUnavailableError"]
