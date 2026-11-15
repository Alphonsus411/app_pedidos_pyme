# F4.11 — Cierre de calidad del catálogo público (propuesta de gate)

Fecha de corte: 2026-11-15. Alcance: **prototipo de consulta pública** del panel React y API HTTP versionada; no certificación de producto ni habilitación de funciones privadas.

## Evidencia de integración verificada

| Incremento | PR fusionada | Alcance |
| --- | --- | --- |
| F4.01 | #122 | Paginación pública |
| F4.02 | #123 | E2E Chromium + FastAPI/SQLite sintético |
| F4.03 | #124 | Presentación de campos reales, moneda y ausencia de disponibilidad inferida |
| F4.04 | #125 | Detalle local de artículo |
| F4.05 | #126 | E2E real de detalle |
| F4.06 | #127 | Atributos ARIA del detalle |
| F4.07 | #128 | Anuncios de paginación y conservación de foco |
| F4.08 | #129 | Foco tras última página |
| F4.09 | #130 | Deduplicación y cursor repetido |
| F4.10 | #131 | Reintento explícito tras HTTP 503 |

La CI del commit de la PR #131 se verificó en verde antes de su squash merge: workflow Python 3.11/3.12 `43743103798` y workflow del panel `43743103799`. Las verificaciones de CI son evidencias de esos commits, **no** una auditoría de seguridad o WCAG.

## Matriz de aceptación

| Criterio | Evidencia automatizada | Estado |
| --- | --- | --- |
| GET público versionado, sin Authorization ni rutas staff | Playwright sintético y con FastAPI real | Cubierto en laboratorio |
| Catálogo vacío, fallo de lectura inicial | Playwright | Cubierto en laboratorio |
| Cursor, segunda página, fin de páginas | Playwright sintético y real | Cubierto en laboratorio |
| Formato de moneda y datos opcionales sin inventar disponibilidad | Node y Playwright | Cubierto en laboratorio |
| Detalle expandible sin peticiones adicionales | Playwright sintético y real | Cubierto en laboratorio |
| Activación de detalle y paginación con teclado | Playwright | Cubierto parcialmente; no auditoría WCAG |
| Duplicados, página vacía y cursor repetido inmediato | Playwright | Cubierto en laboratorio |
| Error transitorio 503 y reintento manual | Playwright | Cubierto en laboratorio |
| Identidad, permisos y sesiones de personal | No se implementa identidad productiva | **Fuera del gate; bloqueo productivo** |
| Persistencia y recuperación duraderas en producción | SQLite temporal y pruebas sintéticas | **Fuera del gate; bloqueo productivo** |

## Riesgos y deuda técnica

1. Los cursores cíclicos de longitud mayor que uno no se detectan; solo se bloquea la repetición inmediata.
2. El estado accesible no constituye conformidad WCAG: faltan auditorías manuales, lector de pantalla y dispositivos reales.
3. Los datos de demostración no prueban aislamiento ni seguridad de una implantación multiempresa real.
4. No existe identidad real de personal ni autorización de endpoints privados; deben continuar deshabilitados.
5. No hay garantías de persistencia productiva, observabilidad, restauración ni despliegue.
6. Las cifras históricas del ROADMAP y DEVELOPMENT_STATUS no equivalen a cierre de gates de dominio/infraestructura.

## Decisión propuesta

**Candidato a gate de laboratorio del catálogo público**, sujeto a CI verde de esta PR documental y revisión humana. No declarar listo para producción ni cambiar versión semántica. Tras aprobar el gate, priorizar diseño de identidad y permisos reales, límites de transacción duradera y contratos de pedidos/reservas. Mantener SQLite solo para desarrollo/pruebas, clientes únicamente vía API HTTP y prohibición de desplegar.

## Reproducción de los controles

Desde el repositorio: ejecutar el workflow de Python para 3.11/3.12 con pytest, Ruff y Mypy, y el workflow del panel con `npm test`, Playwright Chromium, Playwright Chromium + FastAPI/SQLite sintéticos y `npm run build`. Revisar resultados de Actions para el SHA exacto de esta PR; no sustituirlos por éxitos históricos.
