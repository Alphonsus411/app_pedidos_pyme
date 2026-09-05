# ADR-002 — Estrategia multi-tenant y aislamiento

## Estado
**Aceptado.** Definido en Entrega 0.1.

## Contexto
SaaS: múltiples empresas / grupos empresariales / franquicias comparten la
misma instancia del software. Hay que decidir **cómo se aíslan los datos**,
qué entidades llevan `tenant_id`, `business_id`, `location_id`, y la
definición exacta de **Tenant** (¿entidad legal? ¿cuenta SaaS?).

Jerarquía obligatoria: **Tenant → Business → Location**.

## Alternativas consideradas
| Alternativa | Descripción |
|---|---|
| A. Aislamiento **físico**: 1 base de datos por tenant, o 1 schema por tenant. |
| B. Aislamiento **lógico por columna**: todas las tablas llevan `tenant_id`; filtro obligatorio en repositorios. Redundancia intencional. |
| C. **Híbrido**: tenants grandes en DB dedicada, pequeños en columna. |

## Decisión
**Opción B (lógico por columna)** con extensiones:

1. **Redefinición semántica de Tenant**:
   > Tenant es el límite superior de aislamiento, propiedad y separación de
   > datos dentro de la plataforma SaaS.
   
   Tenant **no** es sinónimo de persona jurídica. Puede representar una
   empresa, un grupo empresarial, una franquicia, una cuenta SaaS individual
   o una organización con varias unidades operativas.
2. **Redundancia intencional** de `tenant_id` en TODAS las entidades
   operacionales (incluidas las subordinadas a Business/Location). Objetivo:
   ningún filtro de aislamiento requiere JOIN.
3. **Filtros obligatorios en repositorios**: no existe `list()` sin contexto.
   La mínima firma es `list_by_tenant(tenant_id, ...)` o equivalente.
4. **Tenancy explícita en Repository Ports (RC1 — Hardening):** ninguna
   operación de lectura/listado/búsqueda/modificación/borrado sobre entidades
   *tenant-scoped* puede invocarse sin `tenant_id` explícito en la firma
   del Protocol. Entidades subordinadas (`Location`, `Resource`, `Customer`)
   incluyen además `business_id` y/o `location_id` cuando el contexto lo
   requiere para garantizar el boundary.
   - Excepción documentada: `ITenantRepository` no es tenant-scoped y queda
     excluido de este requerimiento (gestiona el propio límite SaaS).
5. **Verificación arquitectónica AT-9:** `tests/architecture/test_architecture_boundaries.py`
   inspecciona dinámicamente la firma de cada `Protocol` vía `inspect.signature`
   y falla si `tenant_id` falta en un método de acceso de repositorio
   tenant-scoped.
6. **Matriz de tenancy** por entidad (regla de codificación):

| Entidad | tenant_id | business_id | location_id |
|---|---|---|---|
| Tenant | PK | - | - |
| Business | ✅ OBLIGATORIO | PK | - |
| Location | ✅ OBLIGATORIO (redundante) | ✅ OBLIGATORIO | PK |
| Customer | ✅ OBLIGATORIO | ✅ OBLIGATORIO | ⚠️ **OPCIONAL, NO identidad** |
| CatalogItem | ✅ | ✅ | ⚠️ opcional |
| Resource | ✅ | ✅ | ✅ OBLIGATORIO |
| Reservation / Order / Fulfillment | ✅ | ✅ | ✅ OBLIGATORIO |
| DomainEvent | ⚠️ opcional | ⚠️ opcional | ⚠️ opcional |

## Consecuencias
- ✅ Operacionalmente simple: una sola base de datos.
- ✅ Fácil razonar sobre aislamiento (siempre hay un `tenant_id` presente).
- ✅ (RC1) Las firmas de los Repository Ports protegen explícitamente el
  aislamiento: no existe `get()`, `list()` o `search()` en repositorios
  tenant-scoped sin `tenant_id` en la firma.
- ✅ (RC1) El test arquitectónico AT-9 detecta automáticamente firmas de
  repositorio peligrosas que omiten contexto de tenancy (inspección dinámica
  via `inspect.signature` sobre cada Protocol de `domain/**/ports.py`).
- ⚠️ Un bug de implementación (no de firma) en un repositorio concreto aún
  podría omitir el filtro → mitigado: tests unitarios de repositorios falsos
  y tests de integración en FASE 1.
- ⚠️ Si en el futuro un tenant requiere compliance GDPR/SOC2 con aislamiento
  físico, se añade la opción C como ruta de migración (fuera de 0.1).
