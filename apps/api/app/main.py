"""Punto de entrada del adaptador HTTP local, sin rutas de negocio todavía."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    """Construye la API local sin acoplarla al núcleo ni a un cliente concreto."""
    app = FastAPI(
        title="Universal Business API",
        version="0.1.0-prototype",
        description="Adaptador local del prototipo; no preparado para producción.",
    )

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "universal-business-api"}

    return app


app = create_app()
