# F4.04 — Detalle público de artículo (laboratorio)

La API HTTP versionada existente ofrece `GET /api/v1/public/businesses/{businessSlug}/locations/{locationSlug}/catalog` con `items` y paginación por cursor; no existe un endpoint público individual de detalle. Por tanto, el panel permite expandir y ocultar **los datos ya recibidos** del artículo, sin nuevas solicitudes HTTP. No es una página de detalle independiente ni garantiza recuperar artículos no cargados.

La vista muestra únicamente nombre, descripción, precio y disponibilidad cuando los suministra explícitamente la respuesta. Reutiliza el formateador F4.03, mantiene el selector privado deshabilitado, no guarda credenciales y no introduce mutaciones, endpoints nuevos ni accesos a SQLite desde React.

Prueba Playwright con catálogo sintético: expansión, cierre, datos visibles, ausencia de disponibilidad inferida y ausencia de llamadas HTTP privadas. Validar además `npm test`, Playwright Chromium, Chromium + FastAPI + SQLite sintéticos, `npm run build`, y CI Python 3.11/3.12 (pytest, Ruff, Mypy). SQLite solo para desarrollo y pruebas. No desplegar ni fusionar antes de CI verde.
