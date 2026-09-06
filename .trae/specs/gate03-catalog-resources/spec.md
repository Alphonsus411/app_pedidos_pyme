# Especificación — Gate 0.3 Catalog & Resources

**Proyecto:** Universal Business Core (`universal_business`)
**Rama objetivo:** `feat/fase-2-catalog-resources`
**Baseline de referencia:** `master @ c6a4327` (incluye Gate 0.1 + Gate 0.2 merges)
**HEAD inicial de la fase:** `c6a4327` (árbol limpio)
**Ciclo de vida spec:** Draft → Approved → Implemented → Reviewed

---

## 1. Problema, usuarios y objetivos

### 1.1 Problema
Gate 0.2 dejó la Application Layer operativa (Commands / Queries / Handlers / UnitOfWork / IdempotencyStore / DomainEventDispatcher / EventPublisher / execute_use_case). Pero el dominio de `catalog/` y `resources/` es skeleton mínimo:
- `CatalogItem` tiene `CatalogItemType` enum cerrado (PRODUCT/SERVICE/BUNDLE/DIGITAL/OTHER) con semántica confusa, no hay abstraction Offering genérica.
- No existe `CatalogCategory` de agrupación.
- No existe pricing básico (Money) ligado al catálogo offering.
- No existe lifecycle status para category.
- No existe scope location_ids para offering.
- `ResourceType` es enum cerrado (TABLE/ROOM/STAFF/EQUIPMENT/SLOT/OTHER) con nombres sectoriales: viola la agnosticidad.
- No existe entidad `ResourceType` configurable por tenant/business.
- `Resource` tiene `location_id` obligatorio (debería ser opcional para abstraer capacidades business-scoped).
- No hay Offering ↔ ResourceType relation de capacidad requerida (OfferingResourceRequirement).
- No hay domain events específicos de catalog/resources.
- No hay repository ports para Category, Offering separado, ResourceType.
- No hay application use cases reales para catalog/resources.

### 1.2 Usuarios / Quién consume esto
- Diseñadores de casos de uso futuros (Orders / Reservations): necesitan Offering + Resource ya listos para referenciar.
- Verticales concretos que se registrarán (ADR-005): necesitan poder crear tipos de recursos propios y categorías sin tocar el core.
- Host/Infrastructure: necesitan ports Protocol para implementar repositorios reales sin romper el core.

### 1.3 Objetivos Gate 0.3
A) Catalog domain usable: Offering abstraction, pricing básico, status lifecycle, scope locations, Category grouping, OfferingResourceRequirement relation.
B) Resources domain usable: ResourceType entidad configurable (no enum), Resource con lifecycle/status, opcional location_id, capacity opcional.
C) Repository Ports nuevos: IOfferingRepository, ICatalogCategoryRepository, IResourceTypeRepository, IResourceRepository (ampliado). Todos con tenant_id explícito.
D) Domain events: OfferingCreated/Activated/Deactivated/Archived/PriceChanged, CategoryCreated, ResourceCreated/Activated/Deactivated/Archived/AssignedToLocation, ResourceTypeCreated.
E) Application use cases reales (Commands + Queries + Handlers) para catalog y resources usando Gate 0.2 Foundation (UnitOfWork + Idempotency + execute_use_case + post-commit dispatch/publish).
F) Tests de dominio, aplicación y arquitectura completos.
G) Todo sector-agnostic. Sin names vertical-específicos.

### 1.4 Non-goals (explícitamente NO)
- NO Orders / Reservations / Fulfillment / Payments / API / Persistence real / Notifications.
- NO FastAPI / SQLAlchemy / DB drivers / Alembic / Redis / Kafka / Celery.
- NO stock físico complejo / promociones / impuestos complejos / delivery.
- NO Availability Engine (calendarios, slots, conflictos, exclusiones).
- NO frameworks web ni runtime dependencies nuevas (`dependencies = []`).
- NO verticales concretos (restaurante, clínica, peluquería, hotel, retail).
- NO SKU avanzado, variantes complejas, bundles, modifiers, combos, addons.
- NO price lists, pricing por canal, cupones, descuentos, tarifas horarias.
- NO geolocalización avanzada.
- NO Gate 0.4 ni siguientes.

---

## 2. Constraints / Reglas innegociables (§0 spec usuario)

### 2.1 Rule — Rama y baseline
- Rama obligatoria `feat/fase-2-catalog-resources`; NO modificar master; NO merge; NO tags/releases/PyPI.
- Baseline `master @ c6a4327`.

### 2.2 Rule — Zero runtime dependencies nuevas
`dependencies = []` en `pyproject.toml`. Ningún paquete runtime nuevo.

### 2.3 Rule — Sin infraestructura real ni API
- NO FastAPI/Starlette/Flask/Django.
- NO SQLAlchemy/Alembic/DB drivers.
- NO PostgreSQL/SQLite/MySQL/Redis.
- NO Kafka/RabbitMQ/Celery.
- NO WhatsApp/Twilio/Firebase.
- NO OpenAI/Anthropic.
- NO frontend.

### 2.4 Rule — Sin lógica vertical específica
Ninguna lógica de restaurante, clínica, peluquería, hotel, retail.
AT-6 FORBIDDEN_VERTICAL_NAMES intacta: tokens `peluqu`, `clinic`, `clinica`, etc., prohibidos.

### 2.5 Rule — Sin vertical Orders/Reservations
- No implementar pedidos, reservas, disponibilidad avanzada agenda, stock físico complejo, promociones complejas, impuestos complejos, delivery, pagos.

### 2.6 Rule — Mypy strict + Ruff intactos
NO relajar mypy strict. NO silenciar Ruff sin justificación. `# type: ignore` cero. `# noqa` justificados solo estrictamente necesarios.

### 2.7 Rule — Architecture tests existentes AT-1..AT-17 intactos y pasando.

### 2.8 Rule — Tenancy explícito
`tenant_id` explícito en: entities tenant-owned, commands, queries, repository calls, idempotency, events. NO contextvars implícitos. NO singletons. Toda mutation fetch verifica `requested tenant_id == entity.tenant_id`.

---

## 3. Functional Requirements (FRs)

### 3.1 Domain / Catalog — Offering
**Rule FR-1:** Existirá agregado `Offering` con al menos: `offering_id` (OfferingId), `tenant_id`, `business_id`, `name` (non-empty trimmed), `description` (optional str), `status` (lifecycle DRAFT/ACTIVE/INACTIVE/ARCHIVED), `category_id` (optional CatalogCategoryId), `base_price` (optional Money), `location_ids` (frozenset[LocationId] vacío = business-wide scope), `metadata` (MappingProxyType).
**Rule FR-2:** `Offering` hereda `BaseEntity[OfferingId]` + lifecycle methods: `activate()`, `deactivate()`, `archive()`.
**Rule FR-3:** `Offering.create(...)` → emite `OfferingCreated`. `activate()` → emite `OfferingActivated`. `deactivate()` → `OfferingDeactivated`. `archive()` → `OfferingArchived`. `change_base_price(new_price)` → `OfferingPriceChanged`.
**Rule FR-4:** Archived Offering no vuelve a ACTIVE salvo que se documente la semántica como no permitida (preferencia: archived es estado terminal por defecto; si se intenta activate/deactivate sobre archived → InvariantViolationError).
**Rule FR-5:** change_base_price requiere misma currency si ya había precio. Se emite PriceChanged.
**Rule FR-6:** location_ids validado: todas LocationId, no duplicates. Vacío = disponible en todo el business.

### 3.2 Domain / Catalog — CatalogCategory
**Rule FR-7:** Aggregate `CatalogCategory`: `category_id`, `tenant_id`, `business_id`, `name`, `description` optional, `status`, `parent_category_id` optional.
**Rule FR-8:** Regla: `category_id != parent_category_id` (self-parent no permitido).
**Rule FR-9:** CategoryCreated event on create.
**Rule FR-10:** Status lifecycle DRAFT/ACTIVE/INACTIVE/ARCHIVED, reutilizando Status VO existente o enum.

### 3.3 Domain / Offering ↔ Resource Relationship
**Rule FR-11:** Value object o entidad simple `OfferingResourceRequirement` con: `offering_id`, `resource_type_id`, `quantity_required` (>= 1), `required_flag: bool`.
**Rule FR-12:** quantity_required >= 1. Si quantity_required <= 0 → InvariantViolationError.

### 3.4 Domain / Resources
**Rule FR-13:** `ResourceType` como **entidad agregada configurable** (NO enum cerrado). Campos: `resource_type_id`, `tenant_id`, `business_id`, `name` (non-empty), `description` optional, `status`. Evento `ResourceTypeCreated`.
**Rule FR-14:** ResourceType status lifecycle DRAFT/ACTIVE/INACTIVE/ARCHIVED. Eliminar `ResourceType(StrEnum)` de `resources/value_objects.py` (con compatibilidad mínima si es posible; preferencia: eliminar totalmente si no rompe ATs existentes; si hay que mantener compatibilidad, deprecar pero no usar).
**Rule FR-15:** `Resource` actualizado: `resource_type: ResourceType` → `resource_type_id: ResourceTypeId`. `location_id: LocationId` obligatorio → opcional (`LocationId | None = None`). Añadir methods activate/deactivate/archive/touch.
**Rule FR-16:** Resource events: ResourceCreated, ResourceActivated, ResourceDeactivated, ResourceArchived, ResourceAssignedToLocation (cuando se asigna location_id).

### 3.5 Domain / Strong IDs nuevos
**Rule FR-17:** Añadir a `shared/value_objects/ids.py`:
- `OfferingId(BaseStrongId)`
- `CatalogCategoryId(BaseStrongId)`
- `ResourceTypeId(BaseStrongId)`
Actualizar `__all__`.

### 3.6 Repository Ports
**Rule FR-18:** `IOfferingRepository` (Protocol): `get(*, tenant_id, business_id, offering_id) -> Offering | None`, `save(offering) -> None`, `list_by_business(*, tenant_id, business_id, location_id=None, status=None) -> list[Offering]`, `list_active(*, tenant_id, business_id, location_id=None) -> list[Offering]`.
**Rule FR-19:** `ICatalogCategoryRepository`: `get`, `save`, `list_by_business(*, tenant_id, business_id, status=None, parent_category_id=None) -> list`.
**Rule FR-20:** `IResourceTypeRepository`: `get`, `save`, `list_by_business(*, tenant_id, business_id, status=None) -> list`.
**Rule FR-21:** `IResourceRepository` (actualizar el existente): `get(*, tenant_id, business_id, resource_id) -> Resource | None` (ampliado con business_id; no solo location_id), `save`, `list_by_business(*, tenant_id, business_id, location_id=None, status=None, resource_type_id=None)`, `list_active(*, tenant_id, business_id, location_id=None, resource_type_id=None)`, `list_by_location` (mantener si existe).
**Rule FR-22:** Todos los ports usan Protocol @runtime_checkable si se desea, pero mínimo Protocol structural. Todos los métodos de list/filter requieren `tenant_id` explícito y `business_id` cuando corresponda.

### 3.7 Domain Events (§14)
**Rule FR-23:** Todos los eventos heredan de `DomainEvent` y llevan `aggregate_id`, `aggregate_type`, `tenant_id`, `business_id`, cuando corresponda `location_id`.
Events que deben existir:
- OfferingCreated, OfferingActivated, OfferingDeactivated, OfferingArchived, OfferingPriceChanged
- CatalogCategoryCreated
- ResourceTypeCreated
- ResourceCreated, ResourceActivated, ResourceDeactivated, ResourceArchived, ResourceAssignedToLocation

### 3.8 Application / Use cases Catalog
**Rule FR-24:** Subpackage `application/catalog/` con archivos: `__init__.py`, `commands.py`, `queries.py`, `handlers.py`.
**Rule FR-25:** Commands (todos frozen dataclass, con tenant_id, business_id explícitos, idempotency_key opcional IdempotencyKey):
- CreateOffering
- ActivateOffering
- DeactivateOffering
- ArchiveOffering
- ChangeOfferingPrice
- CreateCatalogCategory
**Rule FR-26:** Queries (frozen dataclass):
- GetOffering
- ListOfferingsByBusiness
- ListOfferingsByLocation
- ListActiveOfferings
- ListCategoriesByBusiness
**Rule FR-27:** Handlers usan UnitOfWork, repositorios fake inyectados por constructor. Usa `execute_use_case` donde aplique (mutaciones). Queries NO usan UoW.
**Rule FR-28:** Idempotency aplicada solo a creates (CreateOffering, CreateCatalogCategory): `reserve → handler.execute → complete; except → release → raise`.

### 3.9 Application / Use cases Resources
**Rule FR-29:** Subpackage `application/resources/` con archivos: `__init__.py`, `commands.py`, `queries.py`, `handlers.py`.
**Rule FR-30:** Commands:
- CreateResourceType
- CreateResource
- ActivateResource
- DeactivateResource
- ArchiveResource
- AssignResourceToLocation
**Rule FR-31:** Queries:
- GetResource
- ListResourcesByBusiness
- ListResourcesByLocation
- ListActiveResources
- ListResourceTypesByBusiness
**Rule FR-32:** Idempotency aplicada solo a creates (CreateResourceType, CreateResource).
**Rule FR-33:** AssignResourceToLocation valida business_id del resource coincide y emite ResourceAssignedToLocation.

### 3.10 Validaciones dominio §19
**Rule FR-34:** names non-empty strings, trimmed.
**Rule FR-35:** IDs correctos (todos BaseStrongId).
**Rule FR-36:** tenant_id y business_id obligatorios en todas las entities.
**Rule FR-37:** category parent != self.
**Rule FR-38:** quantity_required >= 1.
**Rule FR-39:** status transitions válidas (archived no vuelve a active/deactivate).
**Rule FR-40:** Money correcto sin float. currency coherente en price change.
**Rule FR-41:** resource assignment coherente (no cross-tenant/business).

### 3.11 Application cross-tenant protection §20
**Rule FR-42:** Toda operación mutable que haga fetch de una entity existente, compara `entity.tenant_id == command.tenant_id`. Si no coincide → lanzar `ApplicationError` / cross-tenant denied.

---

## 4. Non-functional requirements (NFRs)

### NFR-1 Rule — Python 3.11 y 3.12 compatibles.
### NFR-2 Rule — mypy src strict: Success 0 issues.
### NFR-3 Rule — ruff check . → All checks passed!
### NFR-4 Rule — ruff format --check . → 0 files would be reformatted.
### NFR-5 Rule — pytest -q 100% pass (tests anteriores + nuevos).
### NFR-6 Rule — AT-1..AT-22 todos pasando.
### NFR-7 Rule — Git diff --check 0 whitespace errors.
### NFR-8 Rule — Scope audit: cambios concentrados en `domain/catalog/`, `domain/resources/`, `application/catalog/`, `application/resources/`, `tests/`, `docs/`. 0 implementaciones en `infrastructure/`, `api/`, `verticals/` (salvo __init__.py skeleton que no se toca).
### NFR-9 Rule — Grep §32 prohibiciones (fastapi|starlette|sqlalchemy|alembic|redis|celery|kafka|pika|openai|anthropic|stripe|twilio|firebase) → 0 imports reales en `src/universal_business/**` excepto docstrings justificables.
### NFR-10 Rule — Trabajar en waves descritas §34: Wave1 domain+entities/events → Wave2 ports/tests → Wave3 application → Wave4 arch tests/docs → Wave5 quality gate/commit/push.

---

## 5. Acceptance Criteria (33 items §33 AC checklist)

Cada criterio = `rule` o `rubric`:

| # | Criterio §33 | Tipo | Pass condition |
|---|---|---|---|
| AC-1 | Offering funcional | rule | Aggregate Offering existe + lifecycle methods + fields completos |
| AC-2 | Category funcional | rule | CatalogCategory existe + parent!=self validation + status |
| AC-3 | pricing básico funcional | rule | Offering.base_price Money opcional + change_base_price method |
| AC-4 | ResourceType funcional | rule | ResourceType como entidad configurable (no enum) |
| AC-5 | Resource funcional | rule | Resource actualizado con resource_type_id, location_id opcional |
| AC-6 | lifecycle correcto | rule | Offering/Category/ResourceType/Resource activations OK; archived no vuelve active |
| AC-7 | Offering ↔ ResourceType requirement funcional | rule | OfferingResourceRequirement existe; quantity_required>=1 validation |
| AC-8 | Repository Ports completos | rule | 4 nuevos ports Protocol; todos tenant_id explícito |
| AC-9 | tenant isolation explícito | rule | handlers cross-tenant mutation denied; events tienen tenant_id |
| AC-10 | Commands implementados | rule | 12 commands catalog+resources existen frozen |
| AC-11 | Queries implementadas | rule | 10 queries catalog+resources existen frozen |
| AC-12 | handlers usan Foundation 0.2 | rule | UnitOfWork + execute_use_case + repos; idempotency en creates |
| AC-13 | UnitOfWork correctamente usado | rule | mutaciones dentro context manager; commit exitoso → post-commit dispatch/publish |
| AC-14 | idempotency en creates | rule | 4 commands create tienen reserve/complete path |
| AC-15 | release on failure | rule | idempotency store.release() llamado en excepción creates |
| AC-16 | DomainEvents correctos | rule | 14 events catalog+resources existen y son DomainEvent subclases frozen |
| AC-17 | no events before commit | rule | application handlers NO emiten/publish antes commit; 1 test prueba evento no publicado sin commit |
| AC-18 | no infraestructura real | rule | grep §32 0 reales; ports sin implementación |
| AC-19 | no API | rule | FastAPI etc. grep 0 |
| AC-20 | no Orders | rule | 0 archivos/entities/application orders nuevos |
| AC-21 | no Reservations | rule | 0 archivos/entities/application reservations nuevos |
| AC-22 | no Availability Engine | rule | domain/availability sin cambios (salvo skeleton touch mínimo) |
| AC-23 | dependencies = [] | rule | pyproject.toml dependencies = [] |
| AC-24 | mypy strict PASS | rule | mypy src exit 0 |
| AC-25 | Ruff PASS | rule | ruff check . exit 0 |
| AC-26 | Ruff format PASS | rule | ruff format --check . exit 0 |
| AC-27 | pytest PASS | rule | python -m pytest -q exit 0 |
| AC-28 | Python 3.11 PASS | rubric | Scale 0-2: 2=entorno 3.11 pasa todos tests; 1=warning pero no falla; 0=falla. Threshold=2 |
| AC-29 | Python 3.12 PASS | rubric | Scale 0-2: 2=pasaría; 1=warning; 0=falla. Threshold=2 (documentado: CI matrix lo cubre) |
| AC-30 | docs actualizados | rule | DEVELOPMENT_STATUS bumped 0.3.0; ARCHITECTURE.md sección catalog+resources; plan_entrega_0.3_catalog_resources.md creado |
| AC-31 | scope 0.4+ no iniciado | rule | 0 cambios infrastructure/api/verticals concretos |

---

## 6. Assumptions
A1) Gate 0.2 Foundation está 100% mergeado a master baseline c6a4327: Command/Query/Handlers Protocol, UnitOfWork Protocol, IdempotencyStore con método `release()`, DomainEventDispatcher, EventPublisher, execute_use_case helper, VerticalExtension registry atómico.
A2) `CatalogItem` skeleton 0.1 puede permanecer (legacy) pero NO se toca. Offering es el agregado nuevo principal (sugerencia: re-exportar CatalogItem también en ports si hace falta no romper imports).
A3) `ResourceType(StrEnum)` existente en `resources/value_objects.py` se puede eliminar o dejar deprecado pero no usarse en nuevos Resource; nueva entidad `ResourceType` agregada usa ResourceTypeId ID fuerte. Si existe código que importa ResourceType enum: mínimo cambio para no romper.
A4) `Money` Gate 0.1 se usa sin cambios: Decimal 10 prec 4 escala, Currency ISO 3 letras.
A5) `DomainEvent` Gate 0.1 frozen dataclass con aggregate_id/type/tenant_id/business_id/location_id + metadata MappingProxyType se usa para todos los events sin modificar la base.
A6) Architecture tests AT-6 FORBIDDEN_VERTICAL_NAMES tokens ("peluqu", "clinic", "clinica", "pica", "pollo", "restaura", "hotel", "retail", "médica", "médico", "pelu") siguen activos; nuevos módulos catalog/resources NO pueden tener nombres prohibidos ni docstrings que los mencionen.
A7) CI workflow ya cubre push `feat/**` pattern (hardening 0.2 lo cambió). No necesita update excepto si lo requiere el usuario; el spec lo mantiene sin cambios.
A8) El usuario NO requiere Approve explícito por feedback directo en sesiones anteriores; después de escribir spec/tasks, pasamos a Implement directamente (igual que hardening 0.2).

---

## 7. Open Questions / Deferreds
Q1) ¿Mantener `CatalogItem` legacy? DECISION: SÍ mantenerlo intacto (no touch), no deprecar aún; Offering es paralelo sin relación forzada.
Q2) ¿Mantener `ResourceType(StrEnum)` legacy? DECISION: Mantener en value_objects.py sin tocarlo (evita romper imports existentes si hubiera); NUEVA entidad agregada `resources/entities.py: ResourceType` (mismo nombre? Riesgo collision! → Mejor: RENAME legacy enum a `LegacyResourceTypeStrEnum` si hay conflicto. Alternativa: poner nueva entidad ResourceType en mismo archivo entities.py, asegurarse que no haya imports conflictivos. Como mínimo: dejar el enum existente intacto pero NO usarlo en Resource nuevo; Resource usa resource_type_id: ResourceTypeId.)
Q3) OfferingResourceRequirement: ¿es aggregate propio o value object dentro de Offering? DECISION: VO simple con referencia por ID (no necesita persistencia separada todavía; se puede añadir en Gate 0.5 infra).
Q4) ¿Añadir ADR-010 Offering as universal catalog abstraction? DECISION: Si ADR-003 lo cubre parcialmente, actualizar ARCHITECTURE.md con sección nueva; crear ADR-010 solo si hay una decisión arquitectónica significativa nueva que ADR-003 no tocó.
