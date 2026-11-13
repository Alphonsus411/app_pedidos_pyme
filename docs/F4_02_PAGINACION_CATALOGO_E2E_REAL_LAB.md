# F4.02 — Paginación real de catálogo en navegador con FastAPI y SQLite sintéticos

**Alcance:** reforzar el recorrido funcional público ya implementado en F4.01 mediante un test de integración real de navegador, sin introducir escritura, autenticación ficticia ni despliegues.

## Implementación

- El servidor efímero de `tests/integration/f3_browser_api.py` ahora crea **51 ofertas activas exclusivamente sintéticas** del primer negocio y una del segundo negocio con ámbito independiente. Se conserva la arquitectura y la versión del contrato HTTP existente.
- La API pública sirve por defecto hasta 50 artículos en la primera página e incluye `next_cursor`. El navegador React consume ese cursor pulsando **Cargar más artículos**, recupera la oferta restante y después oculta el botón.
- La prueba `apps/business_panel/e2e-real/catalog.spec.js` usa **Chromium + Vite + FastAPI + SQLite real y temporal**: verifica los 50 elementos iniciales, 51 después de cargar la página, presencia de un GET con `?cursor=`, ausencia de peticiones privadas o Authorization y selector de personal deshabilitado.
- Se actualiza la prueba de aislamiento entre dos negocios para reconocer la nueva cantidad de ofertas del primero y conservar la comprobación independiente del segundo.
- No se añade ningún producto o precio real ni se altera el motor, esquema o API.

## Gates y límites

La PR debe superar el workflow frontend de `npm test`, Playwright con respuestas sintéticas, **Playwright con API real sintética** y `npm run build`, además de pytest/Ruff/mypy en Python 3.11 y 3.12.

La prueba no es un despliegue ni valida accesibilidad integral, identidad real, pedidos o catálogos con actualizaciones concurrentes. SQLite sigue limitado a desarrollo y pruebas. El panel privado y cualquier mutación permanecen deshabilitados.
