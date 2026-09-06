# ADR-010 — Offering como abstracción universal de catálogo

## Estado
**Accepted.** Definido e implementado en Gate 0.3 (Catalog & Resources).

## Contexto
En Gate 0.1 el módulo `domain/catalog/` introdujo una entidad mínima `CatalogItem`
con un diseño orientado a producto físico:

```python
# Gate 0.1 — CatalogItem (placeholder / skeleton)
class CatalogItem:
    catalog_item_id: CatalogItemId
    tenant_id: TenantId
    business_id: BusinessId
    name: str
    type: CatalogItemType  # <- ENUM discriminador: PRODUCT / SERVICE
    price: Money
    status: CatalogItemStatus
```

Problemas detectados para el objetivo de **core agnóstico multi-vertical**:

1. **Discriminador `type: CatalogItemType(Enum)` cerrado** no escala a verticales
   genéricas: ¿dónde encajan "turno de peluquería", "alquiler habitación por noche",
   "entrada evento", "paquete turístico", "suscripción mensual", "consulta médica"?
   Añadir valores al Enum por cada vertical rompe el principio de core agnóstico.

2. **`price: Money` OBLIGATORIO** no admite: servicios de precio variable,
   productos bajo cotización, prestaciones sin precio directo (incluidas en otro
   paquete o fijadas por regla).

3. **Sin scope de disponibilidad** (location_ids): los ítems de catálogo de
   Gate 0.1 son business-wide forzado, cuando en la práctica un producto/servicio
   solo se ofrece en una sede concreta.

4. **Sin relación con Resources** (ADR-006): en Gate 0.1 no existe forma de
   expresar "1 'Turno corte' requiere 1 unidad de ResourceType='Silla barbero'".

5. **Lifecycle demasiado simple**: `ACTIVE / INACTIVE` no cubre borrador (DRAFT)
   sin publicar, ni archivo histórico con auditoría de cuándo se retiró.

Decisión de diseño: **NO eliminar `CatalogItem`** en Gate 0.3 (riesgo de romper
referencias internas o externas, incluso teóricas). Se introduce una nueva entidad
en paralelo que los futuros Gates consumirán de forma preferente.

## Alternativas consideradas

| # | Estrategia | Ventajas | Inconvenientes |
|---|---|---|---|
| A | **Mantener CatalogItem, añadir fields ad-hoc + extender Enum** | Cero cambios de nombre | Enum cerrado sigue siendo una pared; `price: Money` obligatorio requiere hacks (0.00 con flag "precio variable"); rompe semántica. |
| B | **Eliminar CatalogItem y reemplazarlo EN SITIO por nueva implementación** | Limpieza máxima | Breaking change para cualquier consumidor; tests Gate 0.1 que referencian `CatalogItem` habría que reescribirlos; riesgo regresión invisible. |
| C | **Entidad NUEVA `Offering` EN PARALELO. CatalogItem legacy marcado como deprecated pero intacto.** (Seleccionada) | BC 0 con Gate 0.1/0.2. Futuros Gates (Orders 0.4) usan Offering sin deuda. Permite migración gradual. | Duplicidad temporal de conceptos en el código. |

Sobre el diseño de la nueva entidad `Offering`:

| Sub-decisión | Opción seleccionada | Razón |
|---|---|---|
| ¿Discriminador `type`? | **NO.** Sin discriminador. | Semántica viene dada por: atributos + categorías asociadas + resource requirements. |
| `base_price: Money` | **OPCIONAL `\| None`** | Permite servicios ad-hoc / cotización / pricing externo. |
| Scope de disponibilidad | **`location_ids: frozenset[LocationId]`** (vacío = business-wide) | Frozenset: inmutable, hashable, no se puede manipular sin método transicional. |
| Lifecycle status | **4 estados: `DRAFT / ACTIVE / INACTIVE / ARCHIVED`** | DRAFT = no publicado; ACTIVE = visible a clientes; INACTIVE = temporalmente fuera; ARCHIVED = histórico (no volver a ACTIVE). |
| Relación con Resource | **Entidad puente `OfferingResourceRequirement` (quantity_required >= 1)** | Explícita y auditable; un Offering puede necesitar N tipos de recursos. |
| ResourceType | **ENTITY configurable (NO enum)** | Cada tenant define sus propios tipos sin tocar código core (ADR-006). |
| Resource.location_id | **OPCIONAL `\| None`** | Permite recursos itinerantes / business-wide (ej: "Doctor" que cubre varias sedes, o equipo de reparto). |

## Decisión

**Opción C: nueva entidad `Offering` paralela + `CatalogItem` legacy intacto.**

Reglas vinculantes de Gate 0.3+:

1. **Agregado `Offering`** (en `domain/catalog/entities.py`):
   - Identidad fuerte `OfferingId`.
   - Lifecycle `OfferingStatus.DRAFT → ACTIVE ↔ INACTIVE → ARCHIVED` (validado por `StatusTransition`).
   - `base_price: Money | None` (siempre `None` o moneda coherente con la moneda base del business si se define).
   - `location_ids: frozenset[LocationId]`; vacío `frozenset()` = disponible en todas las locations del business.
     Invariante: no se admite un `LocationId` que pertenezca a otro `(tenant_id, business_id)`.
   - `category_ids: frozenset[CatalogCategoryId]` (agrupación navegacional).
   - Métodos transicionales: `activate()`, `deactivate()`, `archive()`, `assign_to_locations(...)`,
     `set_base_price(...)`, `add_category(...)`, `remove_category(...)`.
   - Emite eventos del módulo (8 totales).

2. **`CatalogItem` legacy (Gate 0.1)** conservado intacto:
   - Misma clase, mismos atributos, mismos métodos.
   - No se añaden campos nuevos ni se eliminan existentes.
   - **Marcado implícitamente deprecated** por el hecho de que futuros módulos
     (Orders / Reservations) referencien `Offering`, no `CatalogItem`.
   - `ICatalogRepository` Gate 0.1 se mantiene con sus métodos; los métodos
     nuevos (Offering/Category/Requirement) son **aditivos**.

3. **`ResourceType` ENTITY configurable, NO enum** (ADR-006 actualizada):
   - Antes Gate 0.1: `Resource` tenía un `resource_type: ResourceType(Enum)` cerrado
     ("CHAIR", "TABLE", "ROOM", etc.).
   - Ahora Gate 0.3: `ResourceType` es una entidad con `ResourceTypeId`, `code: str`
     unique business-wide, `name`, `is_perishable`, `capacity_per_unit`. El `Resource`
     apunta por FK a `ResourceType.resource_type_id` (OBLIGATORIO).

4. **`Resource.location_id` OPCIONAL (`None` permitido)**:
   - `None` = recurso business-wide (no asignado a una sede concreta), itinerante,
     o sin ubicación fija (ej: vehículo de reparto, personal que rota sedes).
   - Método `assign_to_location(location_id: LocationId | None)` → valida tenant/business
     del location si no es `None`.

5. **Relación Offering ↔ ResourceType** mediante entidad `OfferingResourceRequirement`:
   - `offering_id` FK + `resource_type_id` FK + `quantity_required: int >= 1`.
   - Invariante: ambos lados deben tener mismo `(tenant_id, business_id)`.

6. **Events (14 total) + Application contracts (12 cmd + 10 qry + 22 handlers)**:
   - Mantenidas las reglas de Gate 0.2: frozen dataclass kw_only, handlers de create
     con `IdempotencyStore.reserve` y `execute_use_case` helper.

## Consecuencias

Positivas:
- ✅ **Core verdaderamente agnóstico.** Sin Enum discriminador cerrado. Cualquier
  vertical (restaurante, clínica, hotel, peluquería, suscripciones SaaS, alquileres)
  se modela con la misma entidad Offering + sus categorías + resource requirements.
- ✅ **Backwards compatibility 100% con Gate 0.1/0.2.** `CatalogItem` sigue ahí.
  Ningún test existente de Gate 0.1/0.2 debe fallar por eliminación.
- ✅ **Pricing flexible.** `base_price: None` abre puerta a reglas de pricing
  externas sin forzar monto fijo en el dominio.
- ✅ **Resource management robusto.** `ResourceType` ENTITY permite al tenant crear
  sus propios recursos sin releases del core; `location_id=None` cubre itinerancia.
- ✅ **Futuros Gates 0.4+ tienen una base sólida.** `OrderLine.offering_id`,
  `Reservation.offering_id`, `AvailabilityRule.resource_type_id` quedan definidos
  semánticamente.

Trade-offs y deuda a gestionar en Gates posteriores:
- ⚠️ **Duplicidad conceptual temporal entre `CatalogItem` y `Offering`.** Riesgo:
  que alguien use `CatalogItem` en código nuevo por costumbre. Mitigación: todos
  los módulos futuros (Orders, Reservations, API endpoints) documentan y usan
  **solo `Offering`**. Eventualmente (Gate 0.5/0.6), cuando `CatalogItem` no tenga
  referencias internas ni públicas, se podrá marcar deprecated formalmente y borrar.
- ⚠️ **`base_price: None` no protege contra "no sé el precio" en un Order.**
  Resolución: Gate 0.4 introducirá `PricingResolver` Port para determinar el precio
  real al crear un OrderLine (reglas, cupones, contratos específicos). Offering
  define el *precio base sugerido* o nada.
- ⚠️ **`Resource.location_id = None` complica búsquedas por sede.** Las queries
  de "recursos disponibles en Location X" deben incluir explícitamente los recursos
  `location_id=None` business-wide. Esto se documenta en el `IResourceRepository`
  y se testea en tests unitarios.
- ⚠️ **Sin implementación de check unique `code` por business en ResourceType /
  `slug` por business en CatalogCategory en el dominio.** El dominio define la
  regla como invariante documental; la garantía real corresponderá al adapter de
  persistencia (unique index DB en Gate 0.5). El Port puede declarar un método
  `code_exists(...)` para que el handler verifique antes de guardar.
