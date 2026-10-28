"""Política de transición de reservas, sin efectuar adjudicaciones."""

from __future__ import annotations

from types import MappingProxyType

from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.shared.errors import StatusTransitionError

_ALLOWED: MappingProxyType[ReservationStatus, frozenset[ReservationStatus]] = MappingProxyType(
    {
        ReservationStatus.DRAFT: frozenset(
            {ReservationStatus.CONFIRMED, ReservationStatus.CANCELLED}
        ),
        ReservationStatus.CONFIRMED: frozenset(
            {ReservationStatus.CHECKED_IN, ReservationStatus.CANCELLED, ReservationStatus.NO_SHOW}
        ),
        ReservationStatus.CHECKED_IN: frozenset({ReservationStatus.COMPLETED}),
        ReservationStatus.COMPLETED: frozenset(),
        ReservationStatus.CANCELLED: frozenset(),
        ReservationStatus.NO_SHOW: frozenset(),
    }
)


def allowed_reservation_transitions(source: ReservationStatus) -> frozenset[ReservationStatus]:
    """Devolver destinos válidos sin modificar la reserva."""
    if not isinstance(source, ReservationStatus):
        raise StatusTransitionError("El estado de origen debe ser ReservationStatus")
    return _ALLOWED[source]


def validate_reservation_transition(source: ReservationStatus, target: ReservationStatus) -> None:
    """Rechazar transiciones inválidas; validar no confirma ni adjudica recursos.

    La confirmación efectiva requiere un caso de uso que adjudique el recurso
    atómicamente conforme al contrato de disponibilidad. La repetición del
    mismo estado no es una transición y debe tratarse por idempotencia.
    """
    if not isinstance(target, ReservationStatus):
        raise StatusTransitionError("El estado de destino debe ser ReservationStatus")
    if target not in allowed_reservation_transitions(source):
        raise StatusTransitionError(f"Transición de reserva no permitida: {source} -> {target}")


def reservation_occupies_interval(status: ReservationStatus) -> bool:
    """Indicar si el estado bloquea el intervalo original de la reserva.

    COMPLETED conserva la ocupación del intervalo original aunque se complete
    anticipadamente; no modela una liberación anticipada ni modifica un agregado.
    El caso de uso de disponibilidad debe combinar esta política con el solape.
    """
    if not isinstance(status, ReservationStatus):
        raise StatusTransitionError("El estado debe ser ReservationStatus")
    return status in {
        ReservationStatus.CONFIRMED,
        ReservationStatus.CHECKED_IN,
        ReservationStatus.COMPLETED,
    }
