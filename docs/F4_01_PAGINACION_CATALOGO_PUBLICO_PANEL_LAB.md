# Incremento funcional — Paginación pública del catálogo (laboratorio)

**Alcance:** `apps/business_panel`, aplicación React independiente que solo consume la API HTTP pública `/api/v1/public/.../catalog`. El incremento está destinado a mejorar la consulta real de artículos, no a activar personal, pedidos privados ni operaciones de edición.

## Cambios

- `getPublicCatalog()` acepta opcionalmente el cursor opaco `next_cursor` devuelto por el servidor. Valida su forma, limita a 512 caracteres y lo envía exclusivamente como parámetro codificado `cursor` de una petición HTTP GET de catálogo. Nunca acepta URLs ni slugs ajenos como alcance.
- `App.jsx` conserva la primera página y ofrece **Cargar más artículos** cuando el servidor comunica `next_cursor`. Añade artículos sin duplicar IDs ya presentados; un error en la página siguiente mantiene visibles los artículos anteriores y permite reintentar. El control muestra carga y no envía peticiones simultáneas durante ella. Las solicitudes se abortan al desmontar el panel.
- Pruebas HTTP del cliente y Chromium con respuestas sintéticas cubren dos páginas, desaparición del botón cuando no hay más datos, errores de paginación, ausencia de Bearer y ausencia de solicitudes privadas.
- El selector staff sigue **deshabilitado**. No se invoca `getStaffSession` ni `getStaffOrders` desde la UI. Tampoco se introducen cookies, almacenamiento de secretos, escrituras ni datos reales.

## Límites

Los tests de navegador con interceptación de API no sustituyen la validación extremo a extremo con un catálogo grande en el entorno real, ni resuelven paginación estable bajo cambios concurrentes de artículos. El panel sigue en fase prototipo, sin IdP, permisos, administración de catálogo ni despliegue. SQLite continúa limitado a desarrollo/pruebas.

## Gates

`npm test`, `npm run test:e2e`, `npm run test:e2e:real`, `npm run build` en el workflow de frontend de PR, además de CI Python 3.11/3.12. No fusionar sin evidencia de ambos gates.
