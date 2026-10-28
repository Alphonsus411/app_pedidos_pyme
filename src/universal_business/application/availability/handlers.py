"""Consulta informativa de disponibilidad; no adjudica ni persiste reservas."""

from __future__ import annotations

from datetime import date, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from universal_business.application.availability.queries import EvaluateResourceAvailability
from universal_business.application.errors import ApplicationError
from universal_business.domain.availability.evaluation import (
    AvailabilityEvaluation,
    AvailabilityScope,
    evaluate_availability,
)
from universal_business.domain.availability.materialization import materialize_availability_periods
from universal_business.domain.availability.ports import IAvailabilityRepository
from universal_business.domain.business.ports import ILocationRepository
from universal_business.domain.business.value_objects import LocationStatus
from universal_business.domain.reservations.interval import ReservationInterval
from universal_business.domain.reservations.ports import IReservationRepository
from universal_business.domain.resources.ports import IResourceRepository
from universal_business.domain.shared.value_objects.temporal import DateRange, TimeRange


class EvaluateResourceAvailabilityHandler:
    """Leer un snapshot no transaccional; no es autorización para confirmar.

    Los repositorios deben devolver todas las reglas y bloqueos aplicables,
    incluyendo los de location general, y todas las reservas que puedan
    solaparse. La integración real debe garantizar completitud, aislamiento y
    consistencia; confirmar requiere una operación de adjudicación atómica.
    """

    def __init__(
        self,
        *,
        locations: ILocationRepository,
        resources: IResourceRepository,
        availability: IAvailabilityRepository,
        reservations: IReservationRepository,
    ) -> None:
        self._locations = locations
        self._resources = resources
        self._availability = availability
        self._reservations = reservations

    def handle(self, query: EvaluateResourceAvailability, /) -> AvailabilityEvaluation:
        if not isinstance(query.interval, ReservationInterval):
            raise ApplicationError("Intervalo de consulta inválido")
        scope = AvailabilityScope(
            query.tenant_id, query.business_id, query.location_id, query.resource_id
        )
        location = self._locations.get(
            tenant_id=scope.tenant_id, business_id=scope.business_id, location_id=scope.location_id
        )
        if location is None:
            raise ApplicationError("Location no encontrada")
        if (location.tenant_id, location.business_id, location.id) != (
            scope.tenant_id,
            scope.business_id,
            scope.location_id,
        ):
            raise ApplicationError("Location fuera del ámbito solicitado")
        if (
            not isinstance(location.status, LocationStatus)
            or location.status != LocationStatus.OPEN
        ):
            raise ApplicationError("Location no está abierta")
        resource = self._resources.get(
            tenant_id=scope.tenant_id, business_id=scope.business_id, resource_id=scope.resource_id
        )
        if resource is None:
            raise ApplicationError("Resource no encontrado")
        if (resource.tenant_id, resource.business_id, resource.id, resource.location_id) != (
            scope.tenant_id,
            scope.business_id,
            scope.resource_id,
            scope.location_id,
        ):
            raise ApplicationError("Resource fuera del ámbito solicitado o sin location")
        try:
            ZoneInfo(location.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ApplicationError("Zona horaria de location inválida o no disponible") from exc
        # Timezone offsets are strictly less than 24 hours. Query a conservative
        # date superset based on UTC, so offset changes cannot hide a local day.
        first = query.interval.start.date().toordinal()
        last = (query.interval.end - timedelta(microseconds=1)).date().toordinal()
        local_dates = DateRange(
            start=date.fromordinal(max(date.min.toordinal(), first - 1)),
            end=date.fromordinal(min(date.max.toordinal(), last + 1)),
        )
        rules = self._availability.list_rules_for_resource(
            tenant_id=scope.tenant_id,
            location_id=scope.location_id,
            resource_id=scope.resource_id,
            range=local_dates,
        )
        blocks = self._availability.list_blocks(
            tenant_id=scope.tenant_id,
            location_id=scope.location_id,
            range=local_dates,
        )
        existing = self._reservations.list_for_resource_in_range(
            tenant_id=scope.tenant_id,
            location_id=scope.location_id,
            resource_id=scope.resource_id,
            time_range=TimeRange(query.interval.start, query.interval.end),
            status=None,
        )
        windows, blocked = materialize_availability_periods(
            scope=scope,
            location=location,
            rules=rules,
            blocks=blocks,
        )
        return evaluate_availability(
            scope=scope,
            resource=resource,
            requested=query.interval,
            windows=windows,
            blocks=blocked,
            reservations=existing,
            party_size=query.party_size,
        )
