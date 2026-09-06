# Development Status

> Documento de continuidad técnica. Última actualización: 06-sep-2026 (Gate 0.3 Catalog & Resources).
> Propósito: retomar el proyecto en semanas o meses sin depender de memoria de conversación.

---

## Project

| Campo | Valor |
|---|---|
| Nombre | **Universal Business Core** (paquete `universal_business`) |
| Repositorio GitHub | `app_pedidos_pyme` |
| Versión actual (semver) | `0.3.0` (Entrega 0.3 — Catalog & Resources) |
| Stack | Python ≥3.11, pytest ≥8,<9, ruff ≥0.15,<0.16, mypy ≥2.1,<3 |
| Runtime dependencies | **0** (vacío; core puro sin frameworks) |

---

## Current Git State

> **Nota sobre estabilidad:** este documento NO intenta documentar el SHA autoritativo
> de `HEAD` (sería un bucle lógico). Usa los comandos indicados para consultar el estado
> real en el momento de retomar el proyecto.

| Campo | Valor estable | Consulta operativa |
|---|---|---|
| Rama de referencia actual | `feat/fase-2-catalog-resources` | `git branch --show-current` |
| Baseline de entrada Gate 0.3 | `master @ c6a4327` (post-Gate-0.2 merge commit) | `git show c6a4327 --stat` |
| Baseline de entrada Gate 0.2 | `master @ 4947f06` (merge commit Gate 0.1 final) | `git show 4947f06 --stat` |
| Baseline técnico aprobado Gate 0.1 | `7a705fc ("fix: harden Gate 0.1 architectural baseline")` | `git show 7a705fc --stat` |
| HEAD operativo actual | **NO documentado aquí** (cambia con cada commit) | `git rev-parse HEAD` |
| `master` actual | **NO documentado aquí** (cambia tras merge) | `git rev-parse master` |
| Working tree | **NO documentado aquí** (estado transitorio) | `git status --short` |
| Sincronización remota | **NO documentado aquí** (estado transitorio) | `git branch -vv` |

### Commits históricos relevantes (top-down, snapshot del Gate 0.3)

```
* <HEAD actual>                          # consulta con: git log --oneline -1
* <commit Gate 0.3>                      # "feat(catalog+resources): establish Gate 0.3 catalog & resources domain"
* c6a4327 (master)  ←── merge baseline Gate 0.2 (entry point de Gate 0.3)
* <commit Gate 0.2>                      # "feat(application): establish Gate 0.2 foundation layer"
* 4947f06 (master)  ←── merge baseline Gate 0.1 (entry point de Gate 0.2)
* ...                                    # commits documentales Gate 0.1
* 57e7001                                docs: finalize Gate 0.1 audit; pin dev tooling ranges
* ddadd7b                                docs: add project README and development status
*   889fb21                              merge: integrate remote baseline history before RC1
|\
| * 8ba78e1                              auditoria_gate_0_1.txt (solo historial, eliminado en merge)
* | 7a705fc  RC1  fix: harden Gate 0.1 architectural baseline
|/
* 93d3e95                                feat: implement Universal Business Core architectural baseline
* 25fc345 (origin/master baseline init)  chore: initialize Universal Business Core repository
```

### Nota sobre `auditoria_gate_0_1.txt`

El archivo **NO forma parte del árbol actual** (no aparece en `git ls-files`).
Únicamente permanece en el historial Git dentro del commit `8ba78e1`.
El merge commit `889fb21` lo eliminó explícitamente del árbol final.

---

## Current Architecture

Monolito modular DDD con capas segregadas. Dirección única de dependencias:

```
    API / Channels (vacío 0.2)
          │
    Application (Gate 0.2: contracts, UoW, events, usecases, vertical ext.)
          │
    Domain ──── Ports (Protocols, NO implementación)
          │
    Infrastructure (vacío 0.2)

    └── verticals/  ←── dependen HACIA DENTRO, nunca al revés (vacío 0.2)
```

- **Domain-centric / Ports & Adapters.**
- **Multi-tenant lógico** `Tenant → Business → Location` (tenant_id explícito, sin contextvars).
- **Vertical extensions desacopladas** (ADR-005 + `VerticalExtension` Protocol Gate 0.2).
- **Domain agnostic**: nada en `src/universal_business/domain/` ni `application/` conoce nombres de verticales concretas (ej. pica-pollo).
- **Application Layer semántica (Gate 0.2)**:
  - `Command` / `Query` marcadores inmutables (frozen dataclass)
  - `CommandHandler[C,R]` / `QueryHandler[Q,R]` Protocol genéricos
  - `UnitOfWork` Protocol (frontera transaccional lógica; sin commit implícito; error → rollback)
  - `IdempotencyKey` VO + `IdempotencyStore` Protocol (tenant_id posicional-only obligatorio)
  - `DomainEventDispatcher` (registro explícito, orden determinista MRO; dispatch_many eager-validate)
  - `EventPublisher` Port (para futuros Outbox / Kafka / Rabbit / webhooks)
  - `UseCaseHandler[In,Out]` + helper `execute_use_case` (semántica commit-OK → post-commit events)
  - `VerticalExtension` Protocol + `VerticalRegistry` (idempotente por nombre, ordenado)

---

## Completed Milestones

| Hito | Estado | Nota |
|---|---|---|
| E0. Bootstrap de repositorio | ✅ | `25fc345` |
| E1. Estructura 4 capas + verticals + tooling | ✅ | `3bb3738` / `adbdc75` |
| E2. Value Objects compartidos (IDs, Money/Currency, Temporal, Status) | ✅ | `93d3e95` |
| E3. Entidades `Tenant`, `Business`, `Location`, `Customer` | ✅ | `93d3e95` |
| E4. 6 módulos skeleton mínimos (catalog/resources/availability/reservations/orders/fulfillment) | ✅ | `93d3e95` |
| E5. Repository Ports Protocol por dominio (9 `ports.py`) | ✅ | `93d3e95` |
| E6. `AggregateRootMixin` + `DomainEvent` + metadata inmutable | ✅ | `7a705fc` |
| E7. Tests arquitectónicos AT-1..AT-9 (incl. nuevo AT-9 tenancy signatures) | ✅ | `7a705fc` |
| E8. Hardening RC1 (Currency sin whitelist, ports tenancy explícita, mypy strict global) | ✅ | `7a705fc` |
| E9. CI permanente protege `master` + rama feature | ✅ | `.github/workflows/ci.yml` |
| E10. Merge recovery historia (sin rebase) — push normal exitoso | ✅ | `889fb21` |
| E11. Cierre documental formal (README, Development Status) | ✅ | `ddadd7b` |
| E12. Gate 0.1 Final Audit + rangos cerrados dev tooling reproducibles | ✅ | `57e7001` |
| E13. Application Messaging contracts (Command / Query / Handlers Protocol genérico) | ✅ | Gate 0.2 |
| E14. UnitOfWork Port (frontera transaccional lógica, context manager, sin commit implícito) | ✅ | Gate 0.2 |
| E15. Idempotency contracts (IdempotencyKey VO + IdempotencyStore Protocol, tenant_id explícito) | ✅ | Gate 0.2 |
| E16. Domain Event Dispatching lógico (DomainEventHandler Protocol + Dispatcher registro explícito) | ✅ | Gate 0.2 |
| E17. EventPublisher Port (publish / publish_many, para futuros Outbox/Kafka/webhooks) | ✅ | Gate 0.2 |
| E18. Use Case Execution pattern (UseCaseHandler Protocol + execute_use_case helper) | ✅ | Gate 0.2 |
| E19. Vertical Extension contracts (VerticalExtension Protocol + VerticalRegistry) | ✅ | Gate 0.2 |
| E20. Architecture tests AT-11/AT-12/AT-13/AT-17 nuevos (App⊬API, App⊬Verticals, App sin frameworks, Ports son abstracciones) | ✅ | Gate 0.2 |
| E21. ~95 tests unitarios nuevos (Command/Query, UoW, Idempotency, Events, Usecase, Verticals) | ✅ | Gate 0.2 |
| E22. Errors application (ApplicationError, HandlerNotFoundError, IdempotencyConflictError) | ✅ | Gate 0.2 |
| E23. ADRs 008/009 (transaction semantics + dispatch/publish semantics) | ✅ | Gate 0.2 |
| E24. Spec Mode 0.2: spec.md + tasks.md en `.trae/specs/gate02-foundation-application-layer/` | ✅ | Gate 0.2 |
| E25. Entidad Offering (agregado universal de catálogo, lifecycle DRAFT/ACTIVE/INACTIVE/ARCHIVED, base_price Money opcional, scope location_ids frozenset) | ✅ | Gate 0.3 |
| E26. Entidad CatalogCategory (agrupación simple, parent_category_id opcional, self-parent inválido) | ✅ | Gate 0.3 |
| E27. Entidad OfferingResourceRequirement (relación Offering ↔ ResourceType con quantity_required >= 1) | ✅ | Gate 0.3 |
| E28. Entidad ResourceType ENTITY configurable (no enum), status lifecycle propio | ✅ | Gate 0.3 |
| E29. Entidad Resource (resource_type_id obligatorio, location_id opcional, status ACTIVE/INACTIVE/MAINTENANCE/RETIRED/ARCHIVED, assign_to_location method) | ✅ | Gate 0.3 |
| E30. 12 Domain Events de catalog + resources (6 catalog: OfferingCreated/OfferingActivated/OfferingDeactivated/OfferingArchived/OfferingPriceChanged/CatalogCategoryCreated; 6 resources: ResourceTypeCreated/ResourceCreated/ResourceActivated/ResourceDeactivated/ResourceArchived/ResourceAssignedToLocation) | ✅ | Gate 0.3 |
| E31. Application: 12 Commands frozen (catalog 7 + resources 5), 10 Queries frozen, 22 Handlers. El UnitOfWork pertenece al orquestador execute_use_case de la capa application/execution; los handlers de catalog/resources NO entran ni salen del context-manager de UnitOfWork y NUNCA invocan uow.commit(). El commit es exclusivo de execute_use_case. Creates usan IdempotencyStore con hooks post_commit_success/post_rollback. | ✅ | Gate 0.3 |
| E32. Ports actualizados: ICatalogRepository y IResourceRepository con nuevas operaciones | ✅ | Gate 0.3 |
| E33. ~64 tests unitarios nuevos (dominio catalog+resources + aplicación catalog+resources) — total acumulado ~572 tests | ✅ | Gate 0.3 |
| E34. ADR-010: Offering como abstracción universal de catálogo (paralelo a CatalogItem legacy) | ✅ | Gate 0.3 |
| E35. Spec Mode 0.3: spec.md + tasks.md en `.trae/specs/gate03-catalog-resources/` | ✅ | Gate 0.3 |
| E36. docs/plan_entrega_0.3_catalog_resources.md + DEVELOPMENT_STATUS + ARCHITECTURE actualizados | ✅ | Gate 0.3 |

---

## Gate 0.1 — Architectural Baseline

| Gate | Alcance | Estado | Fecha |
|---|---|---|---|
| **Gate 0.1** | Universal Business Core (VOs, entidades, ports, tests arquitectónicos, docs, CI) | ✅ **APROBADO** | 05-sep-2026 |

13 criterios originales G1..G14 cumplidos (coverage baseline).

---

## Gate 0.1-RC1 — Hardening Arquitectónico

| Gate | Alcance | Estado | Fecha |
|---|---|---|---|
| **Gate 0.1-RC1** | Ports tenancy explícita (AT-9), Currency sin whitelist, DomainEvent metadata inmutable, mypy strict global, CI master, fpdf2 en extra docs, scope real 0.1 documentado. | ✅ **APROBADO** | 05-sep-2026 |

21 criterios RC1 G1..G21 del documento de plan v2.1 cumplidos.

---

## Gate 0.2 — Foundation / Application Layer

| Gate | Alcance | Estado | Fecha |
|---|---|---|---|
| **Gate 0.2** | Application Layer real: Commands/Queries, Handlers tipados, UnitOfWork, Idempotency, DomainEvent Dispatcher, EventPublisher Port, UseCase Execution, Vertical Extensions, AT-11/12/13/17. Sin infraestructura real, sin API, sin verticales concretos. | ✅ **DONE / APROBADO** | 06-sep-2026 |

34 criterios de aceptación §24 del `plan_entrega_0.2_foundation.md` cumplidos.
Registro de decisiones: ADR-008 (application transaction semantics), ADR-009 (dispatch/publish semantics).

---

## Gate 0.3 — Catalog & Resources

| Gate | Alcance | Estado | Fecha |
|---|---|---|---|
| **Gate 0.3** | Entidades dominio: Offering (agregado universal), CatalogCategory, OfferingResourceRequirement, ResourceType (ENTITY configurable no enum), Resource (location_id opcional, assign_to_location). Domain Events catalog+resources total 12 (6 catalog: OfferingCreated/OfferingActivated/OfferingDeactivated/OfferingArchived/OfferingPriceChanged/CatalogCategoryCreated; 6 resources: ResourceTypeCreated/ResourceCreated/ResourceActivated/ResourceDeactivated/ResourceArchived/ResourceAssignedToLocation). Application: 12 Commands frozen + 10 Queries frozen + 22 Handlers. El UnitOfWork pertenece al orquestador execute_use_case de la capa application/execution; los handlers de catalog/resources NO entran ni salen del context-manager de UnitOfWork y NUNCA invocan uow.commit(). El commit es exclusivo de execute_use_case. Creates usan IdempotencyStore con hooks post_commit_success/post_rollback. Ports actualizados ICatalogRepository/IResourceRepository. Tests dominio+aplicación (~64 nuevos, total ~572). ADR-010 Offering universal. | ✅ **DONE / APROBADO** | 06-sep-2026 |

Criterios de aceptación §33 del `plan_entrega_0.3_catalog_resources.md` cumplidos.
Registro de decisiones: ADR-010 (Offering como abstracción universal de catálogo).

---

## Technical Validation

Ejecutados por última vez: 06-sep-2026 (Python 3.11, Windows sandbox).

| Verificación | Comando exacto | Resultado |
|---|---|---|
| Tests unit + arquitectura + imports | `python -m pytest -q` | **~572 passed** (508 baseline Gate 0.2 + ~64 tests Gate 0.3) |
| Ruff lint | `ruff check .` | **All checks passed** |
| Ruff formatter | `ruff format --check .` | **~85+ files already formatted** |
| Mypy strict GLOBAL | `mypy src` | **Success: no issues found in ~80+ source files** |
| Import core sin externos | `python -c "import universal_business; print(universal_business.__version__)"` | **`0.3.0`** OK |
| Working tree | `git status` | **clean** |
| Repo sync | `git branch -vv` | **feat/fase-2-catalog-resources (pendiente push a origin)** |
| Git whitespace audit | `git diff --check` | **0 whitespace errors** |
| Scope audit (master...HEAD) | `git diff master...HEAD --name-only \| grep -E "^src/universal_business/(infrastructure\|api\|verticals)/"` | **Empty output** (no tocados) |
| Application forbidden imports | `grep -RniE "fastapi\|starlette\|sqlalchemy\|redis\|celery\|kafka\|pika\|openai\|anthropic\|stripe\|twilio\|firebase" src/universal_business/application/` | **Empty output** |
| Domain forbidden imports (catalog/resources) | `grep -RniE "fastapi\|sqlalchemy\|redis\|celery\|kafka\|stripe\|twilio" src/universal_business/domain/catalog/ src/universal_business/domain/resources/` | **Empty output** |

---

## Current Repository Boundaries

```
src/universal_business/
├── __init__.py               ← version = "0.3.0"
├── api/                      ← SOLO __init__.py (vacío). NO FastAPI.
├── application/              ← GATE 0.2 (contracts) + GATE 0.3 (catalog+resources commands/queries/handlers)
│   ├── __init__.py           ← Re-exports de contratos y helpers.
│   ├── errors.py             ← ApplicationError, HandlerNotFoundError, IdempotencyConflictError.
│   ├── messaging/
│   │   ├── __init__.py
│   │   ├── commands.py       ← Command (frozen dataclass, kw_only, immutable).
│   │   ├── queries.py        ← Query (frozen dataclass, kw_only, immutable).
│   │   └── handlers.py       ← CommandHandler[C,R] / QueryHandler[Q,R] Protocol genérico (@runtime_checkable).
│   ├── unit_of_work.py       ← UnitOfWork Protocol: __enter__/__exit__/commit/rollback.
│   ├── idempotency.py        ← IdempotencyKey VO regex + IdempotencyStore Protocol (tenant_id posicional-only).
│   ├── events/
│   │   ├── __init__.py
│   │   ├── dispatcher.py     ← DomainEventHandler Protocol + DomainEventDispatcher (registro explícito, orden MRO, dispatch_many eager validate).
│   │   └── publisher.py      ← EventPublisher Protocol: publish / publish_many.
│   ├── execution/
│   │   ├── __init__.py       ← UseCaseHandler Protocol + execute_use_case helper (commit-OK → post-commit events).
│   │   └── use_case.py       ← Alias conveniencia re-export.
│   ├── extensions/
│   │   ├── __init__.py       ← VerticalExtension Protocol + VerticalRegistry (idempotente, sorted).
│   │   └── verticals.py      ← Alias conveniencia.
│   ├── catalog/              ← GATE 0.3: 7 Commands frozen, 5 Queries frozen, 12 Handlers (UoW + IdempotencyStore en creates)
│   │   ├── __init__.py
│   │   ├── commands.py       ← CreateOffering, UpdateOffering, ChangeOfferingStatus, ArchiveOffering,
│   │   │                       CreateCatalogCategory, UpdateCatalogCategory,
│   │   │                       AddOfferingResourceRequirement
│   │   ├── queries.py        ← GetOfferingById, ListOfferings, GetCatalogCategoryById,
│   │   │                       ListCatalogCategories, ListOfferingResourceRequirements
│   │   └── handlers.py       ← 12 handlers (7 cmd + 5 qry)
│   └── resources/            ← GATE 0.3: 5 Commands frozen, 5 Queries frozen, 10 Handlers (UoW + IdempotencyStore en creates)
│       ├── __init__.py
│       ├── commands.py       ← CreateResourceType, UpdateResourceType, CreateResource, UpdateResource, ChangeResourceStatus
│       ├── queries.py        ← GetResourceTypeById, ListResourceTypes, GetResourceById, ListResources, ListResourcesByType
│       └── handlers.py       ← 10 handlers (5 cmd + 5 qry)
├── domain/
│   ├── shared/               ← VOs, eventos, base, errores.
│   ├── business/             ← Tenant, Business, Location, Settings, 3 ports.
│   ├── customers/            ← Customer, value objects, port ICustomerRepository.
│   ├── catalog/              ← GATE 0.3 REAL IMPLEMENTATION: Offering (agregado), CatalogCategory, OfferingResourceRequirement.
│   │   │                       Mantiene CatalogItem legacy intacto.
│   │   ├── __init__.py
│   │   ├── entities.py       ← Offering (DRAFT/ACTIVE/INACTIVE/ARCHIVED, base_price Money opc,
│   │   │                       location_ids frozenset scope), CatalogCategory (parent_category_id opc,
│   │   │                       self-parent invalid), OfferingResourceRequirement (quantity_required >= 1)
│   │   ├── events.py         ← 6 eventos catalog: OfferingCreated, OfferingActivated,
│   │   │                       OfferingDeactivated, OfferingArchived, OfferingPriceChanged,
│   │   │                       CatalogCategoryCreated
│   │   ├── ports.py          ← ICatalogRepository (Offering, Category, Requirement ops)
│   │   └── value_objects.py  ← VOs específicos catalog (ej. OfferingStatus, etc.)
│   ├── resources/            ← GATE 0.3 REAL IMPLEMENTATION: ResourceType ENTITY configurable, Resource.
│   │   │                       Mantiene Resource legacy skeleton (ahora real).
│   │   ├── __init__.py
│   │   ├── entities.py       ← ResourceType (ENTITY no-enum, status lifecycle),
│   │   │                       Resource (resource_type_id oblig, location_id opc,
│   │   │                       status ACTIVE/INACTIVE/MAINTENANCE/RETIRED/ARCHIVED, assign_to_location method)
│   │   ├── events.py         ← 6 eventos resources: ResourceTypeCreated, ResourceCreated,
│   │   │                       ResourceActivated, ResourceDeactivated, ResourceArchived,
│   │   │                       ResourceAssignedToLocation
│   │   ├── ports.py          ← IResourceRepository (ResourceType y Resource ops)
│   │   └── value_objects.py  ← VOs específicos resources (ej. ResourceStatus, ResourceTypeStatus)
│   ├── availability/         ← Rule/Block mínimos + ports (sin cambios, skeleton)
│   ├── reservations/         ← Reserva mínima + status enum + port (sin cambios, skeleton)
│   ├── orders/               ← Pedido mínimo + status enum + port (sin cambios, skeleton)
│   └── fulfillment/          ← Fulfillment mínimo + type/status + port (sin cambios, skeleton)
├── infrastructure/           ← SOLO __init__.py. NO repos reales, NO DB.
└── verticals/                ← SOLO __init__.py. NO pica-pollo.
```

Límites de capa PROTEGIDOS por tests arquitectónicos en
[test_architecture_boundaries.py](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/tests/architecture/test_architecture_boundaries.py) (AT-1..AT-9, AT-11..AT-13, AT-17).

---

## Explicitly Not Implemented

TODOS los items siguientes **NO existen y no deben introducirse hasta FASE ≥0.4 con plan
explícito aprobado**:

### Frameworks / Infraestructura
- ❌ FastAPI / Starlette / Flask / Django
- ❌ SQLAlchemy / ORM / Alembic (migrations)
- ❌ PostgreSQL / SQLite / MySQL / drivers DB
- ❌ Redis
- ❌ Kafka / RabbitMQ / brokers de mensajes
- ❌ Celery / RQ / tareas asíncronas distribuídas
- ❌ DI frameworks (injector, dependency_injector, lagom)

### Servicios externos / integraciones
- ❌ WhatsApp / SMS / Twilio
- ❌ Firebase / FCM / push notifications
- ❌ LLM / AI integrations (OpenAI, Anthropic, Gemini…)
- ❌ Payment gateways (Stripe, Mercado Pago, Culqi…)
- ❌ Delivery providers (Uber Eats, Rappi, Glovo…)
- ❌ Frontend: React, React Native, Vue, Svelte…

### Contenido de verticales
- ❌ Vertical pica-pollo (cualquier código, regla, nombre)
- ❌ Cualquier otro vertical implementado (solo `VerticalExtension` contract)

### Lógica funcional
- ❌ Persistencia real (solo Ports Protocol; sin repositories concretos)
- ❌ Orders / Reservations / AvailabilityEngine: implementación real más allá de skeleton
- ❌ Ciclo completo de pedidos / reservas (líneas, impuestos, descuentos)
- ❌ Stock real / Availability scheduling / engine
- ❌ Fulfillment operacional
- ❌ Outbox físico (solo `EventPublisher` Port)
- ❌ EventBus de infraestructura
- ❌ Global tenant context / contextvars / middleware tenant resolver
- ❌ Pricing avanzado / SKU complejos / variantes Offering multi-atributo
- ❌ Payments / integraciones pago
- ❌ API REST / GraphQL / endpoints reales
- ❌ Notifications / WhatsApp / webhooks concretos

### Implementado en Gate 0.2 (ya NO está en esta lista)
- ✅ Messaging contracts: Command / Query (frozen dataclass inmutable)
- ✅ Handlers Protocol: CommandHandler[C,R] / QueryHandler[Q,R]
- ✅ UnitOfWork Port (frontera transaccional lógica; sin commit implícito)
- ✅ Idempotency: IdempotencyKey VO + IdempotencyStore Protocol (tenant_id explícito)
- ✅ DomainEventDispatcher lógico (registro explícito, orden determinista MRO)
- ✅ EventPublisher Port (publish / publish_many)
- ✅ UseCase execution pattern (UseCaseHandler Protocol + execute_use_case helper)
- ✅ VerticalExtension Protocol + VerticalRegistry (idempotente, ordenado)
- ✅ Errors: ApplicationError, HandlerNotFoundError, IdempotencyConflictError

### Implementado en Gate 0.3 (ya NO está en esta lista)
- ✅ Entidad Offering (agregado universal de catálogo: DRAFT/ACTIVE/INACTIVE/ARCHIVED, base_price Money opc, scope location_ids frozenset)
- ✅ CatalogCategory (parent_category_id opcional, self-parent inválido)
- ✅ OfferingResourceRequirement (relación Offering ↔ ResourceType, quantity_required >= 1)
- ✅ ResourceType ENTITY configurable (no enum, no discriminador cerrado)
- ✅ Resource (resource_type_id oblig, location_id opc, status ACTIVE/INACTIVE/MAINTENANCE/RETIRED/ARCHIVED, assign_to_location)
- ✅ 12 Domain Events catalog + resources (6 catalog: OfferingCreated/OfferingActivated/OfferingDeactivated/OfferingArchived/OfferingPriceChanged/CatalogCategoryCreated; 6 resources: ResourceTypeCreated/ResourceCreated/ResourceActivated/ResourceDeactivated/ResourceArchived/ResourceAssignedToLocation)
- ✅ 12 Application Commands frozen (catalog 7 + resources 5)
- ✅ 10 Application Queries frozen (catalog 5 + resources 5)
- ✅ 22 Application Handlers. El UnitOfWork pertenece al orquestador execute_use_case de la capa application/execution; los handlers de catalog/resources NO entran ni salen del context-manager de UnitOfWork y NUNCA invocan uow.commit(). El commit es exclusivo de execute_use_case. Operaciones de create usan IdempotencyStore con hooks post_commit_success/post_rollback.
- ✅ CatalogItem legacy MANTENIDO intacto (no eliminado) — Offering paralelo (ADR-010)
- ✅ Tests dominio (Offering/Category/Requirement + ResourceType/Resource)
- ✅ Tests aplicación (catalog commands/queries/handlers + resources commands/queries/handlers)
- ✅ ADR-010: Offering como abstracción universal

---

## Known Historical Notes

1. **Commit intruso `8ba78e1`**: añadió `auditoria_gate_0_1.txt` 6306 líneas directamente
   al árbol, incumpliendo punto 12 de RC1. Resolución: merge `--no-commit --no-ff` con
   borrado explícito del archivo mediante `git rm -f`. Resultado: archivo conservado
   en historial, **ausente en HEAD actual** (`889fb21`).
2. **`MONEY_ALLOWED_CURRENCIES`**: originalmente whitelist cerrada `{DOP, USD, EUR}`.
   En RC1 se ELIMINÓ completamente. Ahora `Currency` es un value object frozen ISO-4217-like
   de 3 letras alfabéticas uppercase, sin lista cerrada. Hook de host:
   `is_supported_currency()` + `list_supported_currencies()` en `domain/shared/value_objects/money.py`.
3. **Overrides laxos mypy**: originalmente 6 módulos skeleton tenían `strict=false` en
   `[[tool.mypy.overrides]]`. En RC1 se ELIMINARON todos; `strict=true` GLOBAL
   pasa 0 errores para los 47 source files.
4. **DomainEvent metadata**: originalmente `dict[str,Any]` mutable. En RC1 copia defensiva
   convertida a `types.MappingProxyType`; annotation `Mapping[str,Any]`; cualquier
   mutación posterior falla. 4 tests unitarios en `test_status_and_events.py`.
5. **Repository Ports tenancy**: originalmente `ICustomerRepository.get(customer_id)`
   sin contexto. En RC1 TODOS los repos tenant-scoped tienen `tenant_id` explícito
   (keyword-only cuando aplica). Excepción documentada: `ITenantRepository` no es
   tenant-scoped. Verificado por test arquitectónico AT-9 (`inspect.signature` dinámico).

---

## Current Stop Point

> 🛑 **DETENCIÓN DELIBERADA Y CONFIRMADA.**

- Gate 0.1 ✅ DONE / APROBADO
- Gate 0.1-RC1 ✅ DONE / APROBADO
- Gate 0.1 FINAL AUDIT ✅ DONE / APROBADO (06-sep-2026)
- Gate 0.2 Foundation / Application Layer ✅ DONE / APROBADO (06-sep-2026)
- **Gate 0.3 Catalog & Resources ✅ DONE / APROBADO** (06-sep-2026)
- Rama actual: `feat/fase-2-catalog-resources`. Entry baseline: `master @ c6a4327`.
- **NO existe trabajo de FASE 0.4 en curso.**
- **NO hay trabajo pendiente sin commit en esta rama (post Gate 0.3).**
- **Master intacta, sin merge de Gate 0.3.**
- **infrastructure/**, **api/**, **verticals/** siguen skeleton-only (sin cambios respecto a 0.2).

### Roadmap por etapas (estado factual actual)

| Etapa | Alcance detallado | Estado |
|---|---|---|
| **0.1 Architectural Baseline** | Dominio + VOs + Entidades + Ports + Tests AT-1..AT-9 + CI + Docs | ✅ COMPLETE / DONE |
| **0.1-RC1 Hardening** | Tenancy explícita, Currency sin whitelist, metadata inmutable, mypy strict global | ✅ COMPLETE / DONE |
| **0.2 Foundation / Application Layer** | Commands/Queries, Handlers, UnitOfWork Port, Idempotency, Event Dispatcher, EventPublisher Port, UseCase Execution, Vertical Extensions, AT-11/12/13/17 | ✅ COMPLETE / DONE |
| **0.3 Catalog & Resources** | **Offering** agregado universal (DRAFT/ACTIVE/INACTIVE/ARCHIVED, base_price Money opc, scope location_ids frozenset). **CatalogCategory** (parent opc, self-parent inválido). **OfferingResourceRequirement** (quantity_required ≥1). **ResourceType ENTITY configurable no-enum**. **Resource** (resource_type_id oblig, location_id opc, 5-status lifecycle, assign_to_location). 12 Domain Events (6 catalog: OfferingCreated/OfferingActivated/OfferingDeactivated/OfferingArchived/OfferingPriceChanged/CatalogCategoryCreated; 6 resources: ResourceTypeCreated/ResourceCreated/ResourceActivated/ResourceDeactivated/ResourceArchived/ResourceAssignedToLocation). 12 Commands + 10 Queries + 22 Handlers. El UnitOfWork pertenece al orquestador execute_use_case de la capa application/execution; los handlers de catalog/resources NO entran ni salen del context-manager de UnitOfWork y NUNCA invocan uow.commit(). El commit es exclusivo de execute_use_case. Creates usan IdempotencyStore con hooks post_commit_success/post_rollback. Ports ICatalog + IResource actualizados. Tests ~64 nuevos (total ~572). ADR-010. | ✅ **COMPLETE / DONE** |
| **0.4 Orders & Reservations** | Ciclo completo Order / Reservation / OrderLine / Tax / Discount / status lifecycle / cross-references with Offering + Resource + Availability | ⚪ NOT STARTED |
| **0.5 API & Persistence** | FastAPI (endpoints), SQLAlchemy (models/mappings), PostgreSQL, outbox físico, repositories concretos, migrations (Alembic) | ⚪ NOT STARTED |
| **0.6 First Vertical** | Ej. pica-pollo u otro TBD: seed data, business rules sector, vertical extension concrete | ⚪ NOT STARTED |
| **0.7+ Channels & automation** | WhatsApp Business API, webhooks, delivery providers (Uber/Rappi/Glovo), notifications (FCM/SMS), AI integrations | ⚪ NOT STARTED |

Cualquier continuación debe arrancar con el paso "Siguiente paso recomendado"
siguiente, NO continuando directamente en esta rama con código FASE 0.4.

---

## Next Recommended Actions

Orden estricto recomendado al retomar:

1. **Confirmar que el árbol sigue válido:** ejecutar el *Resume Checklist* (abajo).
2. **Auditoría de Gate 0.3 manual humana (opcional):** revisar criterios aceptación §33 del `plan_entrega_0.3_catalog_resources.md`.
3. **Crear PR formal** en GitHub: `feat/fase-2-catalog-resources → feat/architectural-baseline` (o directamente a `master` según política del repo).
4. **Revisar CI del PR**; el workflow `.github/workflows/ci.yml` corre automáticamente en PR a master.
5. **Mergear SOLO si CI está 100% verde** (~572 tests, ruff, format, mypy strict).
6. Después del merge al baseline:
   - Actualizar la rama base (`git checkout feat/architectural-baseline && git pull` o `git checkout master && git pull`).
   - **Crear una NUEVA rama** para Gate 0.4 (nunca seguir escribiendo directamente sobre `feat/fase-2-catalog-resources`). Nombre sugerido: `feat/fase-3-orders-reservations`.
7. **Definir formalmente el scope de Gate 0.4** antes de abrir IDE: escribir plan, criterios de aceptación, Gate 0.4. NO decidir el contenido de FASE 0.4 sobre la marcha.
8. Conservar como inamovibles:
   - Float para dinero (solo `Money` con `Decimal`).
   - Currency sin whitelist.
   - TODOS los repository ports tenant-scoped con `tenant_id` explícito (AT-9).
   - Application Layer NO importa infrastructure / API / verticales (AT-7, AT-11, AT-12).
   - Application Layer sin frameworks/SDK externos (AT-13).
   - UnitOfWork, IdempotencyStore, EventPublisher son Protocol/ABC sin implementación concreta en core (AT-17).
   - Runtime dependencies `[]` (vacío).
   - Offering como agregado de catálogo universal (ADR-010); CatalogItem legacy se conserva sin tocar.
   - ResourceType ENTITY configurable (no enum). Resource.location_id opcional.

---

## Resume Checklist

Al retomar, ejecuta ESTOS comandos y verifica que todo coincide. Si algo cambió,
no continúes sin entender por qué.

### 1. Estado Git

```bash
# Rama actual
git branch --show-current
# Esperado: feat/fase-2-catalog-resources

# Working tree (debe estar limpio)
git status --short
# Esperado: (sin output)

# Sincronización con origin (cuando se haga push)
git branch -vv
# Esperado: feat/fase-2-catalog-resources

# HEAD actual, Gate 0.3 baseline, Gate 0.2 baseline, Gate 0.1 RC1 baseline
git rev-parse HEAD
git show -s --oneline c6a4327
# Esperado entry baseline 0.3: c6a4327 (merge Gate 0.2 final into master)
git show -s --oneline 4947f06
# Esperado entry baseline 0.2: 4947f06 (merge Gate 0.1 final into master)
git show -s --oneline 7a705fc
# Esperado RC1 baseline: 7a705fc fix: harden Gate 0.1 architectural baseline

# Estado actual de master (referencia)
git rev-parse master

# Resumen gráfico 20 commits
git log --oneline --decorate --graph --all -n 20
```

### 2. Validación técnica (ORDEN EXACTO)

```bash
# 1. Tests
python -m pytest -q
# Esperado: ~572 tests passed (508 baseline Gate 0.2 + ~64 tests Gate 0.3)

# 2. Lint
ruff check .
# Esperado: All checks passed!

# 3. Formato
ruff format --check .
# Esperado: ~85+ files already formatted

# 4. Tipado estricto
mypy src
# Esperado: Success: no issues found in ~80+ source files
```

### 3. Scope + imports audit

```bash
# No hay cambios en infrastructure / api / verticals (salvo __init__ que no tocamos)
git diff master...HEAD --name-only | grep -E "^src/universal_business/(infrastructure|api|verticals)/" || true
# Esperado: (sin output)

# Application no contiene imports prohibidos (innombrables)
grep -RniE "fastapi|starlette|sqlalchemy|redis|celery|kafka|pika|openai|anthropic|stripe|twilio|firebase" src/universal_business/application/ || true
# Esperado: (sin output)

# Domain catalog y resources tampoco tienen imports prohibidos
grep -RniE "fastapi|sqlalchemy|redis|celery|kafka|stripe|twilio" src/universal_business/domain/catalog/ src/universal_business/domain/resources/ || true
# Esperado: (sin output)

# Git whitespace
git diff --check
# Esperado: (sin output)
```

### 4. Import + versión

```bash
PYTHONPATH=src python -c "import universal_business; print(universal_business.__version__)"
# Esperado: 0.3.0
```

Si todo lo anterior coincide, Gate 0.3 está estable. Puedes proceder a crear PR
y planificar Gate 0.4. Si `mypy src` no dice `Success`, o si `ruff check` reporta
algo, revisa `git diff` y arregla antes de continuar. No continúes con
`working tree != clean`.
