# F4.05 — Detalle público: prueba E2E con API real sintética

Se añade un escenario Playwright Chromium contra el servidor FastAPI y su SQLite **temporal y sintético** ya preparados por el laboratorio F4.02. La interfaz obtiene el catálogo por `GET /api/v1/public/businesses/demo/locations/main/catalog` y expande un artículo existente sin llamar a ningún endpoint adicional. El test comprueba nombre, precio, ausencia de disponibilidad inventada, cierre del detalle y que todas las llamadas observadas son GET públicos sin cabecera Authorization. El selector privado continúa deshabilitado y localStorage permanece vacío.

No se modifica dominio, esquema, API ni lógica de producción; no se introduce autenticación, pago, pedidos, mutaciones ni despliegue. SQLite exclusivamente para desarrollo/pruebas. Validación requerida antes de fusionar: CI Python 3.11/3.12 pytest/Ruff/Mypy, y frontend npm test, Chromium sintético, Chromium + FastAPI/SQLite sintéticos y build.
