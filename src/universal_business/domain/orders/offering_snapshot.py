"""Captura conservadora de una oferta de catálogo en una línea de pedido."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from universal_business.domain.catalog.entities import Offering
from universal_business.domain.catalog.value_objects import CatalogItemStatus
from universal_business.domain.orders.line import OrderLine
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import BusinessId, LocationId, TenantId
from universal_business.domain.shared.value_objects.money import Money


def capture_offering_line(
    *,
    tenant_id: TenantId,
    business_id: BusinessId,
    location_id: LocationId,
    offering: Offering,
    line_id: UUID,
    quantity: Decimal,
    discount: Money,
    tax: Money,
) -> OrderLine:
    """Copiar datos de una oferta activa accesible en el ámbito indicado.

    La oferta sin precio se rechaza: el precio autorizado alternativo precisa
    una política y un caso de uso aparte. Descuento e impuesto requieren su
    propia autorización, que esta función no proporciona. La lectura de la
    oferta y cualquier escritura deben coordinarse en la capa de aplicación.
    """
    if not isinstance(tenant_id, TenantId) or not isinstance(business_id, BusinessId):
        raise InvariantViolationError("Ámbito tenant/business inválido")
    if not isinstance(location_id, LocationId) or not isinstance(offering, Offering):
        raise InvariantViolationError("Ubicación u oferta inválida")
    if offering.tenant_id != tenant_id or offering.business_id != business_id:
        raise InvariantViolationError("Oferta fuera del ámbito tenant/business")
    if offering.location_ids and location_id not in offering.location_ids:
        raise InvariantViolationError("Oferta no disponible en esta ubicación")
    if offering.status != CatalogItemStatus.ACTIVE:
        raise InvariantViolationError("La oferta debe estar activa")
    if not isinstance(offering.base_price, Money):
        raise InvariantViolationError("La oferta debe tener precio explícito")
    return OrderLine(
        line_id=line_id,
        offering_id=offering.id,
        name=offering.name,
        quantity=quantity,
        unit_price=offering.base_price,
        discount=discount,
        tax=tax,
    )
