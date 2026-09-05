"""Puertos / contratos de repositorio para el módulo customers (Hardening Gate 0.1-RC1).

Customer vive dentro del boundary de Tenant + Business. location_id es a nivel de la
operación (no de la identidad), pero get/search sí requiere tenant_id +
business_id como contexto obligatorio.
"""

from __future__ import annotations

from typing import Protocol

from universal_business.domain.customers.entities import Customer
from universal_business.domain.customers.value_objects import CustomerStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CustomerId,
    LocationId,
    TenantId,
)


class ICustomerRepository(Protocol):
    def get(
        self,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        customer_id: CustomerId,
    ) -> Customer | None: ...
    def save(self, customer: Customer) -> None: ...
    def get_by_external_ref(
        self,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        external_ref: str,
    ) -> Customer | None: ...
    def search(
        self,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId | None = None,
        query: str | None = None,
        status: CustomerStatus | None = None,
        limit: int = 50,
    ) -> list[Customer]: ...


__all__ = ["ICustomerRepository"]
