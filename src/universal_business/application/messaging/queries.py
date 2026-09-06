"""Marcador semántico para mensajes de tipo Query.

Paralelo a :class:`Command` pero semánticamente de **solo lectura**. También
frozen, inmutable, ``kw_only=True``. Igual que commands, los queries pueden
llevar ``tenant_id`` explícito si filtran por tenant (lo habitual).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class Query:
    """Marcador base frozen (inmutable) para queries.

    Subclasifica para cada consulta concreta (mantén ``@dataclass(frozen=True,
    kw_only=True)`` en la subclase por convención)::

        @dataclass(frozen=True, kw_only=True)
        class ListCustomersByBusiness(Query):
            tenant_id: TenantId
            business_id: BusinessId
            limit: int
            offset: int
    """


__all__ = ["Query"]
