"""Universal Business Core - Catalog & Resources (Entrega 0.3).

Dominio agnóstico multi-tenant, sin dependencias de infraestructura.
Application Layer: contracts, UoW, idempotency, events, usecases, vertical ext.
Domain: Business, Customers, Catalog (Offering/Category/ResourceRequirement),
Resources (ResourceType/Resource), availability skeleton, reservations skeleton,
orders skeleton, fulfillment skeleton.
"""

from __future__ import annotations

__version__ = "0.3.0"
__all__ = ["__version__"]
