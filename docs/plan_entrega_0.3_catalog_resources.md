# Plan de Entrega — Gate 0.3: Catalog & Resources

> **Documento contractual de entrega.** Define objetivo, alcance, prerrequisitos,
> entregables, quality gates y criterios de aceptación.
> Última actualización: 06-sep-2026.
> Versión semver del paquete tras entrega: `0.3.0`.

---

## 0. Objetivo

Entregar un **dominio de Catálogo** y un **dominio de Recursos** funcionales,
agnósticos, tipados estrictamente y sin dependencias de infraestructura, junto
con sus correspondientes **contracts de Application Layer** (Commands/Queries/Handlers
frozen) y tests unitarios + de arquitectura. Sentar las bases de entidades que
serán referenciadas por futuros Gates (Orders → Offering, Reservations → Resource,
Availability → ResourceType/Resource).

**NO** entrega: persistencia real, API HTTP, verticales concretas ni frameworks externos.

---

## 1. Prerrequisitos (invariantes antes de empezar)

| Item | Valor | Verificación |
|---|---|---|
| Baseline `master` de entrada | `master @ c6a4327` (merge commit de Gate 0.2 Foundation) | `git show c6a4327 --stat` |
| Rama de trabajo | `feat/fase-2-catalog-resources` (creada desde c6a4327, **NO sobre feat/fase-1-foundation**) | `git branch --show-current` |
| Runtime dependencies del proyecto | `[]` (vacío). PyPI zero-deps. | `pyproject.toml` sección `[project] dependencies` |
| Dev tooling version ranges | `pytest>=8,<9`; `ruff>=0.15,<0.16`; `mypy>=2.1,<3` | `pyproject.toml` `[project.optional-dependencies]` |
| Baseline tests | `python -m pytest -q` → **~508 passed** (Gate 0.2 + 0.1 acumulados) | Ejecutar y confirmar |
| Baseline ruff / format / mypy | `ruff check .` ✅; `ruff format --check .` ✅; `mypy src` strict ✅ | Ejecutar y confirmar |
| Baseline `working tree` | `git status --short` → **vacio** | Ejecutar y confirmar |
| Scope no-desviado previo | `infrastructure/`, `api/`, `verticals/` son solo `__init__.py` | `git ls-files src/universal_business/{infrastructure,api,verticals}/` |
| Spec Mode artefactos | `.trae/specs/gate03-catalog-resources/spec.md` y `tasks.md` existen | `ls` |

---

## 2. Alcance Funcional (ítems A..Q)

### A. Agregado universal `Offering` (catálogo)
- Entidad `Offering` con identidad fuerte `OfferingId`.
- Lifecycle: `OfferingStatus` enum con `DRAFT`, `ACTIVE`, `INACTIVE`, `ARCHIVED`.
- `StatusTransition[OfferingStatus]` valida matriz de transiciones.
- `name: str` non-empty; `description: str | None`.
- `base_price: Money | None` (opcional: permite servicios sin precio fijo o pricing external).
- `location_ids: frozenset[LocationId]` (scope de disponibilidad; `frozenset()` = business-wide).
- Invariante: `location_ids` solo pueden apuntar a `Location` del mismo `(tenant_id, business_id)`.
- `category_ids: frozenset[CatalogCategoryId]` (agrupación, no identidad).
- Métodos: `activate()`, `deactivate()`, `archive()`, `assign_to_locations(...)`,
  `set_base_price(...)`, `add_category(...)`, `remove_category(...)`.

### B. Entidad `CatalogCategory` (agrupación simple)
- `CatalogCategoryId`, `tenant_id`, `business_id` obligatorios.
- `name: str` non-empty; `slug: str | None` opcional.
- `parent_category_id: CatalogCategoryId | None` (jerarquía, solo 1 nivel recomendado pero no forzado).
- Invariante **self-parent inválido**: `parent_category_id != category_id`.
- Método: `reparent_to(new_parent_id)` → valida self-parent.
- `CatalogCategoryStatus`: `ACTIVE / ARCHIVED`.

### C. Relación Offering ↔ ResourceType: `OfferingResourceRequirement`
- Entidad de asociación m:N (un Offering requiere N tipos de recurso; un ResourceType
  se usa en M offerings).
- `quantity_required: int` → **invariante `quantity_required >= 1`**.
- FKs: `offering_id` (Offering) + `resource_type_id` (ResourceType, módulo `resources/`).
- Invariante: Offering y ResourceType deben compartir `(tenant_id, business_id)`.

### D. ResourceType ENTITY configurable (NO enum — decisión clave)
- **NO** `ResourceType(Enum)` cerrado. Es **entidad** con `ResourceTypeId` propio.
- Atributos: `code: str` (unique business-wide), `name: str`, `description | None`,
  `is_perishable: bool` (de un solo uso vs reutilizable), `capacity_per_unit: int >= 1` (default 1).
- `ResourceTypeStatus`: `ACTIVE / INACTIVE / ARCHIVED` + transition validation.

### E. Entidad `Resource` (instancia concreta)
- `resource_id`, `tenant_id`, `business_id`.
- **`resource_type_id: ResourceTypeId` OBLIGATORIO** (FK a ResourceType).
- **`location_id: LocationId | None` OPCIONAL** → `None` significa resource business-wide,
  itinerante o sin ubicación fija.
- `name: str`, `external_ref: str | None`.
- `ResourceStatus` 5 estados: `ACTIVE | INACTIVE | MAINTENANCE | RETIRED | ARCHIVED` + matrix transiciones.
- Método `assign_to_location(location_id)`: valida que `(tenant_id, business_id)` de la location
  coincida; permite `None` (desasignar).

### F. Domain Events — módulo `catalog/` (8 eventos)
- `OfferingCreated` (agregado completo).
- `OfferingUpdated` (delta de campos editables).
- `OfferingStatusChanged` (from_status → to_status).
- `OfferingArchived` (timestamp + motivo si aplica).
- `CatalogCategoryCreated`.
- `CatalogCategoryUpdated`.
- `OfferingResourceRequirementAdded`.
- (Evento extra de Category reparent si se implementa explicitamente).

Todos: frozen dataclass, `event_id` UUID, `occurred_at` aware UTC, `aggregate_id`,
`aggregate_type`, `tenant_id`, `business_id`, `metadata MappingProxyType`.

### G. Domain Events — módulo `resources/` (6 eventos)
- `ResourceTypeCreated`, `ResourceTypeUpdated`, `ResourceTypeStatusChanged`.
- `ResourceCreated`, `ResourceUpdated`, `ResourceStatusChanged`.

Mismos requisitos de inmutabilidad y metadata que F.

### H. Value Objects específicos
- `OfferingId`, `CatalogCategoryId`, `OfferingResourceRequirementId` (IDs fuertes frozen UUID).
- `OfferingStatus`, `CatalogCategoryStatus` (enums + matriz transiciones).
- `ResourceTypeId`, `ResourceId` (IDs fuertes).
- `ResourceTypeStatus`, `ResourceStatus` (enums + matriz).
- VOs reusados desde `domain/shared/`: `TenantId`, `BusinessId`, `LocationId`,
  `Money`, `Currency`, `DateRange`, `TimeRange`, `DomainEvent`, `StatusTransition`.

### I. Repository Ports (Protocol, cerca del dominio propietario)
- `domain/catalog/ports.py`: `ICatalogRepository` → métodos tipados con `tenant_id` obligatorio
  (keyword-only donde aplique) para `get_offering`, `list_offerings`, `add_offering`,
  `update_offering`, `get_category`, `list_categories`, `add_category`,
  `update_category`, `add_requirement`, `list_requirements_for_offering`.
- `domain/resources/ports.py`: `IResourceRepository` → `get_resource_type`,
  `list_resource_types`, `add_resource_type`, `update_resource_type`,
  `get_resource`, `list_resources`, `add_resource`, `update_resource`,
  `list_resources_by_type`.
- `ITenantRepository`, `IBusinessRepository`, `ILocationRepository`,
  `ICustomerRepository` **INTACTOS** (sin cambios) de Gate 0.2.

### J. Application Commands frozen — catalog/ (7)
Todos son `frozen dataclass`, `kw_only=True`, inmutables, heredan de `Command`.
- `CreateOfferingCommand`: `tenant_id`, `business_id`, `name`, `description?`,
  `base_price?`, `location_ids?`, `category_ids?`, **`idempotency_key`**.
- `UpdateOfferingCommand`: `tenant_id`, `business_id`, `offering_id`, campos editables.
- `ChangeOfferingStatusCommand`: `tenant_id`, `business_id`, `offering_id`, `new_status`.
- `ArchiveOfferingCommand`: `tenant_id`, `business_id`, `offering_id`, `reason?`.
- `CreateCatalogCategoryCommand`: idempotency_key, datos básicos + parent?.
- `UpdateCatalogCategoryCommand`: cambios + reparent.
- `AddOfferingResourceRequirementCommand`: offering_id + resource_type_id + quantity_required (>=1).

### K. Application Queries frozen — catalog/ (5)
Todos frozen dataclass, heredan de `Query`.
- `GetOfferingByIdQuery(tenant_id, business_id, offering_id)` → `Offering | None`.
- `ListOfferingsQuery(tenant_id, business_id, status? / category_id? / location_id?)` → `list[OfferingSummary]`.
- `GetCatalogCategoryByIdQuery(tenant_id, business_id, category_id)` → `CatalogCategory | None`.
- `ListCatalogCategoriesQuery(tenant_id, business_id, parent_id?)` → `list[CatalogCategory]`.
- `ListOfferingResourceRequirementsQuery(tenant_id, business_id, offering_id)` → `list[OfferingResourceRequirement]`.

### L. Application Commands frozen — resources/ (5)
- `CreateResourceTypeCommand`: idempotency_key + code/name/description/is_perishable/capacity_per_unit.
- `UpdateResourceTypeCommand`: cambios editables + tenant_id/business_id/resource_type_id.
- `CreateResourceCommand`: idempotency_key + resource_type_id (OBLIG) + location_id (OPC) + name/external_ref.
- `UpdateResourceCommand`: cambios editables.
- `ChangeResourceStatusCommand`: new_status (5-valor).

### M. Application Queries frozen — resources/ (5)
- `GetResourceTypeByIdQuery`, `ListResourceTypesQuery` (status filter optional).
- `GetResourceByIdQuery`, `ListResourcesQuery` (filters: status?, type?, location?).
- `ListResourcesByTypeQuery` (tenant/business + resource_type_id).

### N. Application Handlers (22 total)
TODOS los handlers de **create** deben:
1. Declarar dependencias `UnitOfWork` + `IdempotencyStore` Protocol (no concreta).
2. Hacer `IdempotencyStore.reserve(key, tenant_id/)` antes de escribir.
3. Ejecutar dentro de `execute_use_case` helper (ADR-008):
   UoW enter → handler.handle → uow.commit → exit UoW → dispatcher.dispatch_many →
   publisher.publish_many → return result.
4. Manejar `IdempotencyConflictError` y `ApplicationError` jerarquía.

Breakdown:
- **catalog handlers (12):** 7 command handlers + 5 query handlers.
  - `CreateOfferingHandler` → IdempotencyStore.reserve + UoW.catalog.add_offering → return OfferingReadModel.
  - `UpdateOfferingHandler` → UoW.catalog.update_offering.
  - `ChangeOfferingStatusHandler` → estado transición + save.
  - `ArchiveOfferingHandler` → archiva (invariante: no se des-archiva; status final).
  - `CreateCatalogCategoryHandler` → Idempotency + add_category.
  - `UpdateCatalogCategoryHandler` → update + reparent (self-parent inválido → error).
  - `AddOfferingResourceRequirementHandler` → valida offering+resource_type mismo tenant.
  - 5 Query handlers: retorna datos sin mutar, sin commit (solo read from repo ports).
- **resources handlers (10):** 5 command handlers + 5 query handlers.
  - `CreateResourceTypeHandler` (idempotency).
  - `UpdateResourceTypeHandler`, `CreateResourceHandler` (idempotency, location optional),
    `UpdateResourceHandler`, `ChangeResourceStatusHandler` (5-status matrix).
  - 5 Query handlers correspondientes.

### O. Tests unitarios y de integración lógica (sin DB) — ~64 nuevos
**Dominio catalog/**:
- Offering: lifecycle transiciones válidas/inválidas, invariants location_ids,
  base_price Money same-currency ops si aplica, categories add/remove duplicate,
  activate desde DRAFT y desde INACTIVE; archive desde cualquier estado menos ARCHIVED.
- CatalogCategory: self-parent raise; reparent válido; slug unique por business (si
  implementado a nivel de repo-port).
- OfferingResourceRequirement: quantity_required < 1 → raise; cross-business → raise.
- Events: metadata inmutable MappingProxyType; campos obligatorios (occurred_at aware).

**Dominio resources/**:
- ResourceType: ENTITY no-enum (prueba que no enum subclass); status transiciones;
  capacity_per_unit >= 1.
- Resource: location_id None permitido; assign_to_location mismatched tenant → raise;
  ResourceStatus 5-valor transiciones válidas/inválidas (ej. ACTIVE → MAINTENANCE OK,
  ARCHIVED → ACTIVE NOT ALLOWED, etc.).

**Aplicación catalog/**:
- Cada command handler con Fake UnitOfWork + Fake IdempotencyStore: happy path.
- Idempotency: misma key 2 veces → IdempotencyConflictError al segundo.
- Fallo de commit → rollback, sin eventos post-commit.
- Query handlers: devuelven datos del repo fake; no llaman uow.commit.

**Aplicación resources/**:
- Análogo catalog handlers con sus propios fakes.

**Architecture guards (AT-*):**
- Nuevos AT-* si son necesarios: `domain.catalog ⊬ infrastructure/API/verticals`,
  `domain.resources ⊬ infra`, `application.catalog ⊬ infra`, `application.resources ⊬ infra`.
- AT-9 (tenancy signatures) cubre nuevos repos ICatalog / IResource.
- AT-11 / AT-12 / AT-13 / AT-17 siguen siendo VÁLIDOS (sin romper).

Total tests esperados: **~572 passed** (~508 Gate 0.2 + ~64 Gate 0.3).

### P. Documentación actualizada / nueva
- `DEVELOPMENT_STATUS.md` actualizado: Current Phase = Gate 0.3, Gate 0.1/0.2/0.3 = DONE,
  roadmap 0.4+ NOT STARTED, test count ~572, Resume Checklist actualizado a 0.3.
- `ARCHITECTURE.md` nuevas secciones "Catalog Domain Model" y "Resources Domain Model"
  (después de Foundation, antes de Enlaces).
- `docs/adr/ADR-010.md`: Offering como abstracción universal, CatalogItem legacy intacto.
- **Este documento:** `docs/plan_entrega_0.3_catalog_resources.md`.

### Q. Backwards compatibility & invariants
- `CatalogItem` legacy de Gate 0.1 **NO SE ELIMINA, NO SE MODIFICA** (se conserva intacto
  para no romper consumers internos hipotéticos). Offering es un agregado NUEVO en paralelo.
- `Resource` skeleton de Gate 0.1 **SE REEMPLAZA** por nueva implementation real
  (ya que era un placeholder sin consumers).
- Todos los métodos de `ICatalogRepository` legacy (CatalogItem) se conservan.
  Los nuevos métodos de Offering/Category/Requirement son **aditivos**.
- `pyproject.toml` SIN CAMBIOS de dependencias runtime / tooling. `dependencies = []`.

---

## 3. Entregables (definición de DONE)

Al final de Gate 0.3 deben existir los siguientes archivos en `HEAD`:

```
src/universal_business/
├── __init__.py                                    ← __version__ = "0.3.0"
├── domain/
│   ├── catalog/
│   │   ├── entities.py                            ← Offering, CatalogCategory, OfferingResourceRequirement
│   │   ├── events.py                              ← 8 eventos catalog
│   │   ├── value_objects.py                       ← OfferingStatus, IDs, etc.
│   │   ├── ports.py                               ← ICatalogRepository (additivo, mantiene CatalogItem)
│   │   └── __init__.py
│   └── resources/
│       ├── entities.py                            ← ResourceType (ENTITY), Resource
│       ├── events.py                              ← 6 eventos resources
│       ├── value_objects.py                       ← ResourceTypeStatus, ResourceStatus, IDs
│       ├── ports.py                               ← IResourceRepository
│       └── __init__.py
└── application/
    ├── catalog/
    │   ├── commands.py                            ← 7 Commands frozen
    │   ├── queries.py                             ← 5 Queries frozen
    │   ├── handlers.py                            ← 12 Handlers (7 cmd + 5 qry)
    │   └── __init__.py
    └── resources/
        ├── commands.py                            ← 5 Commands frozen
        ├── queries.py                             ← 5 Queries frozen
        ├── handlers.py                            ← 10 Handlers (5 cmd + 5 qry)
        └── __init__.py

tests/
├── unit/
│   ├── test_domain_catalog_offering.py
│   ├── test_domain_catalog_category.py
│   ├── test_domain_catalog_offering_resource_requirement.py
│   ├── test_domain_resources_resource_type.py
│   ├── test_domain_resources_resource.py
│   ├── test_application_catalog.py
│   └── test_application_resources.py
└── architecture/
    └── test_architecture_boundaries.py            ← nuevos asserts AT catalog/resources

docs/
├── DEVELOPMENT_STATUS.md                          ← actualizado Gate 0.3
├── ARCHITECTURE.md                                ← secciones Catalog+Resources
├── adr/ADR-010.md                                 ← Offering universal
└── plan_entrega_0.3_catalog_resources.md          ← ESTE DOCUMENTO
```

---

## 4. Quality Gates (órden de ejecución CI)

Cada uno **debe pasar 100% verde** antes de considerar Gate 0.3 entregado.

| # | Gate | Comando | Criterio de PASS |
|---|---|---|---|
| QG1 | **pytest** | `python -m pytest -q` | **~572 tests passed**, 0 failed, 0 errors (tolerancia 0). No se permite `xfail` sin comentario justificado en código. |
| QG2 | **ruff lint** | `ruff check .` | `All checks passed!` (0 warnings, 0 errors). |
| QG3 | **ruff format** | `ruff format --check .` | `X files already formatted` (0 reformateos). |
| QG4 | **mypy strict GLOBAL** | `mypy src` | `Success: no issues found in Y source files` (strict=true). 0 `# type: ignore` injustificados. |
| QG5 | **git-diff-check** (whitespace) | `git diff --check` | 0 whitespace errors. |
| QG6 | **scope audit** (forbidden layers) | `git diff master...HEAD --name-only \| grep -E "^src/universal_business/(infrastructure\|api\|verticals)/"` | **Empty output** (no tocar esas capas). |
| QG7 | **grep-forbidden (application layer global)** | `grep -RniE "fastapi\|starlette\|sqlalchemy\|redis\|celery\|kafka\|pika\|openai\|anthropic\|stripe\|twilio\|firebase" src/universal_business/application/` | **Empty output**. |
| QG8 | **grep-forbidden (domain catalog + resources)** | `grep -RniE "fastapi\|sqlalchemy\|redis\|celery\|kafka\|stripe\|twilio\|firebase" src/universal_business/domain/catalog/ src/universal_business/domain/resources/` | **Empty output**. |
| QG9 | **import sin externos** | `PYTHONPATH=src python -c "import universal_business; v=universal_business.__version__; assert v=='0.3.0', v; print(v)"` | Imprime `0.3.0` exit code 0. |
| QG10 | **idempotency signatures check (AT-9 extendido)** | `pytest tests/architecture/ -q -k AT` | Todos los AT-* (incluyendo AT-9 para ICatalog/IResource) pasan. |

---

## 5. Criterios de Aceptación (§33 — 33 items G1..G33)

Criterios contractuales. **Para aprobar Gate 0.3 los 33 deben ser TRUE.**

**Dominio — Offering (G1..G8)**
- G1. `Offering` instanciable con `OfferingId` UUID fuerte, `tenant_id`, `business_id`, `name` non-empty.
- G2. `OfferingStatus` enum 4 valores: `DRAFT, ACTIVE, INACTIVE, ARCHIVED`.
- G3. `StatusTransition[OfferingStatus]` rechaza transiciones inválidas (ej. `ARCHIVED → ACTIVE`).
- G4. `base_price: Money | None` es opcional; si `Money` → validado `Decimal + Currency`.
- G5. `location_ids: frozenset[LocationId]` por defecto `frozenset()` = business-wide.
- G6. Invariante: `offering.location_ids` que incluya un `LocationId` de otro `(tenant_id,business_id)` → raise.
- G7. Métodos `activate()`, `deactivate()`, `archive()` emiten el `OfferingStatusChanged` / `OfferingArchived` correspondiente.
- G8. `Offering` hereda de `AggregateRootMixin` y recolecta eventos en `.events`.

**Dominio — CatalogCategory & OfferingResourceRequirement (G9..G14)**
- G9. `CatalogCategory` admite `parent_category_id=None` y no-null.
- G10. `category.parent_category_id == category.category_id` → ValueError al construir o al `reparent_to`.
- G11. `OfferingResourceRequirement` acepta `offering_id` y `resource_type_id` del mismo tenant.
- G12. `quantity_required = 0` o negativo → raise ValueError.
- G13. `quantity_required = 1` válido; `quantity_required = 100` válido.
- G14. `OfferingResourceRequirement` con offering y resource_type de tenant distinto → raise.

**Dominio — Resources (ResourceType, Resource) (G15..G22)**
- G15. `ResourceType` NO es subclass de `Enum`. `isinstance(rt, Enum)` → `False`.
- G16. `ResourceType` tiene `ResourceTypeId` propio, `code` único por business, `is_perishable: bool`, `capacity_per_unit >= 1`.
- G17. `Resource.resource_type_id` es OBLIGATORIO en constructor. No puede ser `None`.
- G18. `Resource.location_id` acepta `None` sin lanzar error.
- G19. `ResourceStatus` enum 5 valores: ACTIVE, INACTIVE, MAINTENANCE, RETIRED, ARCHIVED.
- G20. `StatusTransition[ResourceStatus]` valida transiciones: ACTIVE→MAINTENANCE (OK), ARCHIVED→ACTIVE (NOK).
- G21. `resource.assign_to_location(location_id)` con location de tenant distinto → raise.
- G22. `resource.assign_to_location(None)` des-asigna y retorna sin error.

**Events & VO (G23..G25)**
- G23. 14 eventos catalog+resources son frozen dataclass, occurent_at tz-aware UTC.
- G24. Cada evento tiene `aggregate_type` string ("Offering", "Resource", "ResourceType", etc.).
- G25. VOs específicos son hashable, frozen, usable como dict key / set members.

**Application Layer — Commands / Queries / Handlers (G26..G30)**
- G26. 12 Commands frozen (7 catalog + 5 resources): son `frozen=True, kw_only=True`, heredan de `Command`.
- G27. 10 Queries frozen: heredan de `Query`, no mutan estado.
- G28. 22 Handlers: cada create handler usa `IdempotencyStore.reserve(key, tenant_id/)` posicional-only.
- G29. Todos los command handlers que escriben usan `execute_use_case` helper (o flujo ADR-008 equivalente explícito).
- G30. Los 3 Idempotency create handlers: llamadas duplicate lanzan `IdempotencyConflictError` sin efecto lateral en UoW.

**Quality Gates + Docs + Invariants (G31..G33)**
- G31. QG1..QG10 PASS 100% (~572 tests, ruff, format, mypy strict, scope, grep, import, AT).
- G32. 4 documentos creados/actualizados: `DEVELOPMENT_STATUS.md`, `ARCHITECTURE.md`, `ADR-010.md`, `plan_entrega_0.3_catalog_resources.md`.
- G33. Invariantes no-desviación: `dependencies = []` en `pyproject.toml`; `CatalogItem` legacy intacto; `infrastructure/`, `api/`, `verticals/` sin código nuevo; `Runtime deps 0`.

---

## 6. Deferred Work (para Gate 0.4+)

TODOS los ítems siguientes **NO forman parte de Gate 0.3** y requieren su propio
plan de entrega formal antes de implementar:

| Grupo | Item | Gate objetivo |
|---|---|---|
| **Orders & Reservations** | Aggregate `Order` completo: `OrderLine`, `OrderStatus` lifecycle, taxes, discounts, totals, reference a `Offering`. Aggregate `Reservation`: overlap detection, waitlist, no-show policy, bind to `Resource` / `Offering`. | 0.4 |
| **Availability Engine** | Motor de scheduling real: `AvailabilityRule`/`Block` con solapamiento, búsqueda de slots libres por `ResourceType` + `DateRange`, capacidad pools (ResourceType.capacity_per_unit * N resources). | 0.4 |
| **Payments** | `Payment` entities, port `IPaymentGateway`, integración Stripe/MercadoPago (abstracta), `PaymentStatus` lifecycle FSM. | 0.5 |
| **API (HTTP / canales)** | FastAPI app, routers catalog/resources/orders/reservations, Pydantic schemas, OpenAPI spec, auth (JWT/OAuth2), tenant resolver header-based. | 0.5 |
| **Persistence** | SQLAlchemy 2.x declarative models, Alembic migrations, PostgreSQL, repositories concretos (implementan Protocol de domain/), UnitOfWork real con session.begin/nested, Outbox físico tabla + worker. | 0.5 |
| **Notifications / WhatsApp** | `INotificationChannel` Port. WhatsApp Business API adapter, SMS/Twilio, FCM push, templates multilingual. | 0.6/0.7 |
| **Verticales concretas** | `verticals/pica_pollo/` o similar: datos semilla, business rules específicos, extensiones de `VerticalExtension` Protocol, tests vertical-specific. | 0.6 |
| **Features catalog avanzadas** | SKU con atributos multi-valor (talla/color), bundles de Offerings, inventario por Offering/variante, pricing rules dinámicas (hora pico / cupones). | 0.4+ opcional |
| **Observabilidad & tooling extra** | Structlog, OpenTelemetry traces, Docker Compose dev stack, pre-commit hooks, Bandit SAST, release/publish PyPI. | 0.5+ (opcional) |

---

## 7. Matriz de responsabilidad (resumen)

| Capa / Área | Gate 0.1 | Gate 0.2 | **Gate 0.3 (ESTE)** | Gate 0.4+ |
|---|---|---|---|---|
| `domain/shared/*` | ✅ | ✅ (sin cambiar) | ✅ (sin cambiar) | Maintenance |
| `domain/business/` + customers | ✅ | ✅ | ✅ (sin cambiar) | Extensión |
| `domain/catalog/` | Skeleton CatalogItem | ✅ (sin cambiar) | **Offering, Category, Requirement + ports + events** | SKU/variants |
| `domain/resources/` | Skeleton Resource | ✅ (sin cambiar) | **ResourceType ENTITY + Resource real + ports + events** | Pools/graphs |
| `domain/availability/` | Skeleton | ✅ | Skeleton (sin cambiar) | **Motor real** |
| `domain/reservations/` + orders + fulfillment | Skeleton | ✅ | Skeleton (sin cambiar) | **Lifecycle completo** |
| `application/messaging/` + errors + uow + idempotency + events + execution + verticals | — (vacío) | ✅ Contracts | ✅ (sin cambiar) | Maintenance |
| `application/catalog/` | — (vacío) | — (vacío) | **7 cmd + 5 qry + 12 handlers** | Nuevos casos uso |
| `application/resources/` | — (vacío) | — (vacío) | **5 cmd + 5 qry + 10 handlers** | Nuevos casos uso |
| `infrastructure/` + `api/` + `verticals/` | Skeleton | Skeleton | Skeleton | **Implementaciones concretas** |
| Tests arquitectura | AT-1..AT-9 | +AT-11/12/13/17 | +AT catalog/resources | Extensión |
| Tests unitarios | ~418 | +~95 = ~515 | **+~64 = ~572** | +∞ |

---

## 8. Siguientes pasos tras aprobar Gate 0.3

1. Merge PR `feat/fase-2-catalog-resources` → `master` (o `feat/architectural-baseline`), CI verde.
2. Tag `v0.3.0` (annotated).
3. Crear rama `feat/fase-3-orders-reservations` DESDE el merge commit.
4. Escribir `plan_entrega_0.4_orders_reservations.md` con objetivo, alcance G1..Gn, quality gates.
5. Crear Spec Mode `gate04-orders-reservations/` si aplica.
