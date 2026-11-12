# F2 — Decisión de gate local para comenzar F3

Estado: **APTO CON RESTRICCIONES para iniciar F3 por incrementos**.
Fecha de revisión: 2026-11-12. Base revisada: `master` `e4212699f6874eb03947d6a11e9558801232b777`.
CI: https://github.com/Alphonsus411/app_pedidos_pyme/actions/runs/43082406779 (Python 3.11/3.12, pytest, Ruff, mypy correctos).

Esta decisión es **solo de desarrollo y prototipo local**, no cierra requisitos de producción ni autoriza despliegues, pagos, notificaciones, datos reales o usuarios externos.

## Evidencia suficiente para el inicio incremental de F3

| Criterio F2 del roadmap | Evidencia disponible | Veredicto |
| --- | --- | --- |
| Catálogo HTTP público versionado | `GET /api/v1/public/businesses/{business_slug}/locations/{location_slug}/catalog`, ámbito resuelto en servidor, cursor y validación | Cumple para prototipo |
| Creación de pedido HTTP | `POST .../orders` crea solo `draft`, precio del servidor, idempotencia, atomicidad multilínea y replay | Cumple para prototipo |
| Consulta staff por ámbito | `GET /api/v1/staff/businesses/{business_slug}/locations/{location_slug}/orders` y `.../orders/{order_id}`, `read_orders` por negocio y ubicación | Cumple para prototipo |
| Errores y correlación | Respuestas de error normalizadas y `X-Request-ID` | Cumple para prototipo |
| Aislamiento y fallos con SQLite real | Pruebas de dos negocios, rechazo 401/403/404, pedidos de otro ámbito, grants sin scope, idempotencia y rollback | Cumple para prototipo |
| Límites HTTP | Validación de cantidades/ítems/clave; limitador local y máximo bruto de bytes **optativos** | Implementación de laboratorio; no mitigación productiva |
| Auditoría | Puerto `StaffAuditSink` optativo y best-effort; sin persistencia | No cumple auditoría productiva |

## Contratos que **NO existen aún** para el panel F3

- Autenticación real de personas, sesión web, expiración/renovación, revocación, recuperación, gestión de secretos o IAM.
- API privada de **escritura/administración de catálogo**; la lectura pública no autoriza edición.
- API privada de **transiciones de pedido**, acciones de confirmación o preparación; la lectura staff no implica permisos de modificación.
- API de selección/listado de negocios y ubicaciones autorizados para el actor, ni módulos activados por negocio.
- Contratos HTTP validados para reservas/personal o permisos de plataforma.
- Auditoría duradera, rate limiting distribuido, reverse proxy y operación de producción.

## Alcance autorizado de F3, primer incremento

Puede comenzar una **aplicación frontend independiente**, consumidora exclusiva de HTTP, con visualización de pedidos *solo lectura* y estados de carga/error, pruebas de aislamiento entre dos negocios y controles de acceso a nivel de servidor ya existentes. Para pruebas automatizadas usar únicamente identidades técnicas y datos sintéticos locales. Nunca incluir tokens estáticos del laboratorio en un bundle público, ni suponer que ocultar botones constituye autorización.

**No habilitar** edición de catálogo, cambios de estado de pedidos, selección dinámica de ámbitos por el usuario o inicio de sesión real mientras no existan los contratos y garantías adecuados. El primer panel puede evolucionar por verticales pequeños: (1) contratos de lectura y pruebas, (2) componente de consulta *read-only*, (3) nuevos endpoints privados de escritura por permiso y pruebas negativas, (4) habilitación de acciones del panel, (5) validación end-to-end.

## Dependencias y criterios de desbloqueo

1. **Antes de exponer el panel a usuarios reales:** IdP y sesiones de servidor verificadas, secretos fuera del navegador, política de revocación y auditoría durable; revisión de privacidad y seguridad.
2. **Antes de administrar catálogo:** comandos HTTP versionados, validación del ámbito por identidad, permisos de escritura diferenciados, conflictos/errores/idempotencia y pruebas de dos negocios.
3. **Antes de mutar pedidos:** definir transiciones permitidas, roles explícitos, eventos y pruebas de atomicidad, concurrencia y rollback.
4. **Antes de declarar F3 completo:** recorrido ficticio negocio → API → panel, dos negocios y varias ubicaciones, verificación de permisos en servidor y pruebas del frontend sin dependencias Python/SQLite.

## Decisión

**F2 local: gate condicional superado para iniciar F3 read-only.**
**F2 como API de producción: gate abierto.**
**F3 gestión de catálogo y pedidos: bloqueada por contratos privados de escritura aún inexistentes.**

No se modifican código fuente, tests ni workflows con esta decisión. Todo trabajo futuro debe seguir en ramas separadas, con CI y revisión antes de integrar a `master`.
