"""Punto de entrada del adaptador HTTP local."""

import re
from decimal import Decimal

from apps.api.app.cors import ApiCorsSettings, install_cors
from apps.api.app.error_contract import install_error_contract
from apps.api.app.public_body_limit import PublicOrderBodySizeMiddleware
from apps.api.app.public_catalog import (
    PublicCatalogCursorInvalid,
    PublicCatalogReader,
    PublicCatalogUnavailable,
)
from apps.api.app.public_orders import PublicOrderItem, PublicOrderRejected, SqlitePublicOrders
from apps.api.app.public_rate_limit import LocalPublicOrderRateLimiter
from apps.api.app.staff_audit import StaffAccessAuditEvent, StaffAuditSink
from apps.api.app.staff_auth import AuthenticationRequired, StaffAuthenticator
from apps.api.app.staff_orders import (
    SqliteStaffOrders,
    StaffOrderNotFound,
    StaffOrdersForbidden,
    StaffOrdersUnavailable,
)
from apps.api.app.staff_session import StaffSessionReader, authorized_staff_scopes
from fastapi import FastAPI, HTTPException, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response


class PublicOrderLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offering_id: str = Field(min_length=36, max_length=36)
    quantity: Decimal = Field(gt=0, le=1000, max_digits=12, decimal_places=4)


class PublicOrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PublicOrderLineIn] = Field(min_length=1, max_length=50)


def create_app(
    *,
    public_catalog: PublicCatalogReader | None = None,
    public_orders: SqlitePublicOrders | None = None,
    cors_settings: ApiCorsSettings | None = None,
    staff_authenticator: StaffAuthenticator | None = None,
    staff_orders: SqliteStaffOrders | None = None,
    staff_audit_sink: StaffAuditSink | None = None,
    staff_session_reader: StaffSessionReader | None = None,
    staff_published_scopes: frozenset[tuple[str, str]] | None = None,
    public_order_limiter: LocalPublicOrderRateLimiter | None = None,
    public_order_max_body_bytes: int | None = None,
) -> FastAPI:
    """Construye la API local con dependencias de infraestructura explícitas."""
    app = FastAPI(
        title="Universal Business API",
        version="0.1.0-prototype",
        description="Adaptador local del prototipo; no preparado para producción.",
    )
    # Registrar primero el limiter: el middleware de correlación exterior
    # instala request_id y conserva X-Request-ID incluso en respuestas 429.
    if public_order_limiter is not None:

        @app.middleware("http")
        async def limit_public_order_requests(
            request: Request, call_next: RequestResponseEndpoint
        ) -> Response:
            if request.method == "POST" and re.fullmatch(
                r"/api/v1/public/businesses/[^/]+/locations/[^/]+/orders",
                request.url.path,
            ):
                client = request.client.host if request.client is not None else "unknown"
                key = f"{client}:{request.url.path}"
                retry = public_order_limiter.retry_after(key)
                if retry is not None:
                    request_id = getattr(request.state, "request_id", "")
                    return JSONResponse(
                        status_code=429,
                        headers={"Retry-After": str(retry)},
                        content={
                            "error": {
                                "code": "rate_limited",
                                "message": "Too many public order requests",
                                "request_id": request_id,
                            }
                        },
                    )
            return await call_next(request)

    if public_order_max_body_bytes is not None:
        # Por dentro del middleware de correlación: 413 conserva X-Request-ID.
        app.add_middleware(PublicOrderBodySizeMiddleware, max_bytes=public_order_max_body_bytes)
    install_error_contract(app)
    install_cors(app, cors_settings)

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "universal-business-api"}

    @app.get(
        "/api/v1/public/businesses/{business_slug}/locations/{location_slug}/catalog",
        tags=["public-catalog"],
    )
    def list_public_catalog(
        business_slug: str,
        location_slug: str,
        limit: int = Query(default=50, ge=1, le=100),
        cursor: str | None = Query(default=None, max_length=512),
    ) -> dict[str, object]:
        if public_catalog is None:
            raise HTTPException(status_code=503, detail="Public catalog is not configured")
        try:
            page = public_catalog.list_active(
                business_slug=business_slug,
                location_slug=location_slug,
                limit=limit,
                cursor=cursor,
            )
        except PublicCatalogUnavailable:
            raise HTTPException(status_code=404, detail="Public catalog not found") from None
        except PublicCatalogCursorInvalid:
            raise HTTPException(status_code=422, detail="Catalog cursor is invalid") from None
        return {"items": page.items, "next_cursor": page.next_cursor}

    @app.post(
        "/api/v1/public/businesses/{business_slug}/locations/{location_slug}/orders",
        status_code=201,
        tags=["public-orders"],
    )
    def create_public_order(
        business_slug: str,
        location_slug: str,
        request: PublicOrderIn,
        idempotency_key: str = Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
        ),
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

    def record_staff_access(
        *,
        request: Request,
        subject: str | None,
        business_slug: str,
        location_slug: str,
        action: str,
        status_code: int,
    ) -> None:
        if staff_audit_sink is None:
            return
        event = StaffAccessAuditEvent(
            request_id=request.state.request_id,
            subject=subject,
            business_slug=business_slug,
            location_slug=location_slug,
            action=action,
            status_code=status_code,
        )
        # Registro best-effort en el prototipo. Un fallo del sink no debe
        # convertir un 401/403 en 500 ni revelar información de identidad.
        try:
            staff_audit_sink.record(event)
        except Exception:
            pass

    @app.get("/api/v1/staff/session", tags=["staff-session"])
    def read_staff_session(request: Request, response: Response) -> dict[str, object]:
        # No se cachea identidad ni permisos. El endpoint no crea sesiones,
        # no recibe grants del navegador y no usa tokens estáticos del lab.
        response.headers["Cache-Control"] = "no-store"
        if staff_session_reader is None or staff_published_scopes is None:
            raise HTTPException(status_code=503, detail="Staff session is not configured")
        try:
            principal = staff_session_reader.current_principal(request)
        except AuthenticationRequired:
            raise HTTPException(status_code=401, detail="Authentication is required") from None
        return {
            "subject": principal.subject,
            "scopes": authorized_staff_scopes(principal, published_scopes=staff_published_scopes),
        }

    @app.get(
        "/api/v1/staff/businesses/{business_slug}/locations/{location_slug}/orders",
        tags=["staff-orders"],
    )
    def list_staff_orders(
        business_slug: str,
        location_slug: str,
        request: Request,
        authorization: str | None = Header(default=None),
        limit: int = Query(default=50, ge=1, le=100),
    ) -> dict[str, object]:
        subject: str | None = None
        status_code = 500
        try:
            if staff_authenticator is None or staff_orders is None:
                status_code = 503
                raise HTTPException(status_code=503, detail="Staff orders are not configured")
            try:
                principal = staff_authenticator.authenticate(authorization)
                subject = principal.subject
            except AuthenticationRequired:
                status_code = 401
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
                status_code = 404
                raise HTTPException(status_code=404, detail="Staff scope not found") from None
            except StaffOrdersForbidden:
                status_code = 403
                raise HTTPException(
                    status_code=403, detail="Access to staff scope is forbidden"
                ) from None
            status_code = 200
            return {"items": items}
        finally:
            record_staff_access(
                request=request,
                subject=subject,
                business_slug=business_slug,
                location_slug=location_slug,
                action="list_orders",
                status_code=status_code,
            )

    @app.get(
        "/api/v1/staff/businesses/{business_slug}/locations/{location_slug}/orders/{order_id}",
        tags=["staff-orders"],
    )
    def get_staff_order(
        business_slug: str,
        location_slug: str,
        order_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        subject: str | None = None
        status_code = 500
        try:
            if staff_authenticator is None or staff_orders is None:
                status_code = 503
                raise HTTPException(status_code=503, detail="Staff orders are not configured")
            try:
                principal = staff_authenticator.authenticate(authorization)
                subject = principal.subject
            except AuthenticationRequired:
                status_code = 401
                raise HTTPException(
                    status_code=401,
                    detail="Authentication is required",
                    headers={"WWW-Authenticate": "Bearer"},
                ) from None
            try:
                result = staff_orders.get_for_location(
                    principal=principal,
                    business_slug=business_slug,
                    location_slug=location_slug,
                    order_id=order_id,
                )
            except StaffOrdersUnavailable:
                status_code = 404
                raise HTTPException(status_code=404, detail="Staff scope not found") from None
            except StaffOrdersForbidden:
                status_code = 403
                raise HTTPException(
                    status_code=403, detail="Access to staff scope is forbidden"
                ) from None
            except StaffOrderNotFound:
                status_code = 404
                raise HTTPException(status_code=404, detail="Staff order not found") from None
            status_code = 200
            return result
        finally:
            record_staff_access(
                request=request,
                subject=subject,
                business_slug=business_slug,
                location_slug=location_slug,
                action="get_order",
                status_code=status_code,
            )

    return app


app = create_app()
