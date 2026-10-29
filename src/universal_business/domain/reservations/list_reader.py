"""Puerto opcional para listados limitados de reservas."""

from typing import Protocol

from universal_business.domain.reservations.entities import Reservation
from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.shared.value_objects.ids import BusinessId, LocationId, TenantId


class ReservationListReader(Protocol):
    """Leer solo registros del ámbito/filtro con límite; no garantiza orden ni paginación.

    El adaptador debe aislar tenant/business/location, aplicar el filtro y
    proporcionar lectura coherente. No debe truncar silenciosamente antes de
    aplicar los filtros. El llamador no puede inferir completitud de una página.
    """

    def list_by_location(
        self,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId,
        status: ReservationStatus | None,
        limit: int,
    ) -> list[Reservation]: ...
