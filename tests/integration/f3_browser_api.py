"""Servidor efímero F3.8: catálogo HTTP FastAPI y SQLite exclusivamente sintéticos.

Solo arranca por invocación explícita desde Playwright. No se usa en despliegues
ni contiene tokens, identidad de empleados, datos personales o secretos.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from apps.api.app.main import create_app
from apps.api.app.public_catalog import PublicCatalogScope, SqlitePublicCatalog

from universal_business.domain.catalog.entities import Offering
from universal_business.domain.catalog.value_objects import CatalogItemStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    OfferingId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money
from universal_business.infrastructure.sqlite_offerings import SqliteOfferingRepository
from universal_business.infrastructure.sqlite_schema import initialize_sqlite_schema
from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork


def run_lab(database: Path) -> None:
    first_tenant, second_tenant = TenantId.generate(), TenantId.generate()
    first_business, second_business = BusinessId.generate(), BusinessId.generate()
    first_location, second_location = LocationId.generate(), LocationId.generate()

    with sqlite3.connect(database) as connection:
        initialize_sqlite_schema(connection)
        with SqliteUnitOfWork(connection) as uow:
            repository = SqliteOfferingRepository(connection)
            repository.save(
                Offering(
                    id=OfferingId.generate(),
                    tenant_id=first_tenant,
                    business_id=first_business,
                    name="Artículo sintético F3.8",
                    status=CatalogItemStatus.ACTIVE,
                    base_price=Money("12.50", "EUR"),
                    location_ids=frozenset({first_location}),
                )
            )
            # 51 active public offerings force an actual second HTTP page
            # with the existing API default limit=50. Entirely synthetic.
            for number in range(1, 51):
                repository.save(
                    Offering(
                        id=OfferingId.generate(),
                        tenant_id=first_tenant,
                        business_id=first_business,
                        name=f"Artículo sintético adicional {number:02d}",
                        status=CatalogItemStatus.ACTIVE,
                        base_price=Money("3.25", "EUR"),
                        location_ids=frozenset({first_location}),
                    )
                )
            repository.save(
                Offering(
                    id=OfferingId.generate(),
                    tenant_id=second_tenant,
                    business_id=second_business,
                    name="Artículo exclusivo segundo negocio",
                    status=CatalogItemStatus.ACTIVE,
                    base_price=Money("9.00", "EUR"),
                    location_ids=frozenset({second_location}),
                )
            )
            uow.commit()

    catalog = SqlitePublicCatalog(
        connect=lambda: sqlite3.connect(database),
        scopes={
            ("demo", "main"): PublicCatalogScope(
                tenant_id=first_tenant,
                business_id=first_business,
                location_id=first_location,
            ),
            ("second", "main"): PublicCatalogScope(
                tenant_id=second_tenant,
                business_id=second_business,
                location_id=second_location,
            ),
        },
    )
    # Solo catálogo público; ni autenticador staff ni sesiones se componen.
    app = create_app(public_catalog=catalog)
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    with TemporaryDirectory(prefix="f3-browser-real-api-") as directory:
        run_lab(Path(directory) / "synthetic.db")
