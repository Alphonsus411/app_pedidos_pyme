"""Punto de entrada del adaptador HTTP local."""

from apps.api.app.public_catalog import PublicCatalogReader, PublicCatalogUnavailable
from fastapi import FastAPI, HTTPException


def create_app(*, public_catalog: PublicCatalogReader | None = None) -> FastAPI:
    """Construye la API local con dependencias de infraestructura explícitas."""
    app = FastAPI(
        title="Universal Business API",
        version="0.1.0-prototype",
        description="Adaptador local del prototipo; no preparado para producción.",
    )

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "universal-business-api"}

    @app.get(
        "/api/v1/public/businesses/{business_slug}/locations/{location_slug}/catalog",
        tags=["public-catalog"],
    )
    def list_public_catalog(business_slug: str, location_slug: str) -> dict[str, object]:
        if public_catalog is None:
            raise HTTPException(status_code=503, detail="Public catalog is not configured")
        try:
            items = public_catalog.list_active(
                business_slug=business_slug,
                location_slug=location_slug,
            )
        except PublicCatalogUnavailable:
            raise HTTPException(status_code=404, detail="Public catalog not found") from None
        return {"items": items}

    return app


app = create_app()
