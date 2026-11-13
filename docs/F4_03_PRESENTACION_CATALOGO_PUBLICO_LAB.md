# F4.03 — Presentación del catálogo público a partir de campos reales de la API

**Alcance:** exclusivamente presentación React del catálogo de solo lectura y pruebas sintéticas. La API pública actual devuelve `id`, `name`, `description` y `price` con `amount` y `currency`; **no devuelve disponibilidad**, por lo que no puede deducirse del estado activo del catálogo.

## Implementación

- `apps/business_panel/src/catalogPresentation.mjs` centraliza `displayPrice`, `displayDescription` y `displayAvailability`.
- Los importes decimales no negativos y finitos acompañados de un código de moneda ISO de tres letras se muestran mediante `Intl.NumberFormat("es-ES", {style:"currency", currency})`. Se evita inventar la moneda o convertir cantidades sin autorización. Si faltan precio o moneda, el panel muestra **Precio no disponible**, no una divisa asumida.
- Una descripción se muestra solo cuando `description` es una cadena no vacía; se respeta el escape de React, sin inyectar HTML.
- La disponibilidad **únicamente** se muestra si la respuesta trae explícitamente `available: true` o `available: false`. El contrato público actual no incluye ese campo, así que en el recorrido real no aparece ninguna etiqueta de disponibilidad.
- La navegación, selección privada y mutaciones siguen deshabilitadas; no se envía ninguna llamada staff desde la interfaz.

## Comprobaciones

- Tests Node del formateador para EUR, USD, JPY, descripción ausente, importe incompleto/inválido y valores de disponibilidad no booleanos.
- Playwright Chromium con respuestas públicas sintéticas que incluyen descripción, disponibilidad explícita y ausencia de metadatos.
- Playwright real con FastAPI y SQLite sintéticos valida que el importe de `12.5000 EUR` se presenta como `12,50 €`, sin cambios del contrato HTTP.
- Gates completos: `npm test`, Chromium E2E, Chromium + FastAPI + SQLite real de laboratorio, build, pytest/Ruff/mypy Python 3.11 y 3.12.

## Limitaciones

No hay comercio, inventario ni disponibilidad productiva; tampoco se incorporan datos reales, identidad, pagos, escritura, despliegue ni modificación del núcleo Python/API/esquema. SQLite exclusivamente para desarrollo y pruebas. El formato de presentación no significa que el precio esté jurídicamente listo para publicar, incluir impuestos o representar stock.
