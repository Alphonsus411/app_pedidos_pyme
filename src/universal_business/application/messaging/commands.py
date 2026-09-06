"""Marcador semántico para mensajes de tipo Command.

En Gate 0.2 **no implementamos ningún bus**, ningún mediador, ningún registry
global. El :class:`Command` es simplemente una frozen dataclass base para que
todos los commands concretos de fases 0.3+ hereden un comportamiento común
(inmutable, ``kw_only=True``).

Los commands **pueden** llevar ``tenant_id`` explícito cuando operan sobre
datos tenant-owned. Jamás se acepta un ``tenant_id`` *implícito* por
contexto/``contextvars`` en Gate 0.2 (regla tenancy Gate 0.1 + AT-9).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class Command:
    """Marcador base frozen (inmutable) para commands.

    Subclasifica para cada comando concreto (mantén ``@dataclass(frozen=True,
    kw_only=True)`` en la subclase por convención)::

        @dataclass(frozen=True, kw_only=True)
        class CreateCustomer(Command):
            tenant_id: TenantId
            business_id: BusinessId
            customer_id: CustomerId
            display_name: str
    """


__all__ = ["Command"]
