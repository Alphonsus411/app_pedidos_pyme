"""Punto de entrada del adaptador HTTP local."""

from decimal import Decimal

from apps.api.app.public_catalog import PublicCatalogReader, PublicCatalogUnavailable
from apps.api.app.public_orders import PublicOrderItem, PublicOrderRejected, SqlitePublicOrders
from apps.api.app.staff_auth import AuthenticationRequired, StaticBearerAuthenticator
from apps.api.app.staff_orders import (
    SqliteStaffOrders,
    StaffOrdersForbidden,
    StaffOrdersUnavailable,
)
from fastapi import FastAPI, HTTPException, Header, Query
from pydantic import BaseModel, ConfigDict, Field


class PublicOrderLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offering_id: str
    quantity: Decimal = Field(gt=0)


class PublicOrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PublicOrderLineIn] = Field(min_length=1)


def create_app(
    *,
    public_catalog: PublicCatalogReader | None = None,
    public_orders: SqlitePublicOrders | None = None,
    staff_authenticator: StaticBearerAuthenticator | None = None,
    staff_orders: SqliteStaffOrders | None = None,
) -> FastAPI:
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

    @app.post(
        "/api/v1/public/businesses/{business_slug}/locations/{location_slug}/orders",
        status_code=201,
        tags=["public-orders"],
    )
    def create_public_order(
        business_slug: str,
        location_slug: str,
        request: PublicOrderIn,
        idempotency_key: str = Header(alias="Idempotency-Key"),
    ) -> dict[str, object]:
        if public_orders is None:
            raise HTTPException(status_code=503, detail="Public orders are not configured")
        try:
            return public_orders.create_draft(
                business_slug=business_slug,
                location_slug=location_slug,
                idempotency_key=idempotency_key,
                items=[
                    PublicOrderItem(offering_id=item.offering_id, quantity=item.quantity)
                    for item in request.items
                ],
            )
        except PublicCatalogUnavailable:
            raise HTTPException(status_code=404, detail="Public catalog not found") from None
        except PublicOrderRejected:
            raise HTTPException(status_code=409, detail="Order request was rejected") from None

    @app.get(
        "/api/v1/staff/businesses/{business_slug}/locations/{location_slug}/orders",
        tags=["staff-orders"],
    )
    def list_staff_orders(
        business_slug: str,
        location_slug: str,
        authorization: str | None = Header(default=None),
        limit: int = Query(default=50, ge=1, le=100),
    ) -> dict[str, object]:
        if staff_authenticator is None or staff_orders is None:
            raise HTTPException(status_code=503, detail="Staff orders are not configured")
        try:
            principal = staff_authenticator.authenticate(authorization)
        except AuthenticationRequired:
            raise HTTPException(
                status_code=401,
                detail="Authentication is required",
                headers={"WWW-Authenticate": "Bearer"},
            ) from None
        try:
            items = staff_orders.list_for_location(
                principal=principal,
                business_slug=business_slug,
                location_slug=location_slug,
                limit=limit,
            )
        except StaffOrdersUnavailable:
            raise HTTPException(status_code=404, detail="Staff scope not found") from None
        except StaffOrdersForbidden:
            raise HTTPException(
                status_code=403, detail="Access to staff scope is forbidden"
            ) from None
        return {"items": items}

    return app


app = create_app()
