# ARCHITECTURE.md — Universal Business Core

## Visión
El **Universal Business Core (UBC)** es un motor empresarial **agnóstico** que,
posteriormente, se extiende mediante verticales sectoriales (ej.: restaurante
de pica-pollo, peluquería, clínica, etc.). El core NO contiene nombres ni
reglas propias de un único sector. Está diseñado como un
**monolito modular** con límites estrictos entre capas y módulos.

## Estilo arquitectónico: Ports & Adapters / 4 capas

```
┌──────────────────────────────────────────────┐
│   API / Channels (HTTP, CLI, WS, móvil)      │  <- api/
├──────────────────────────────────────────────┤
│   Application / Use Cases                    │  <- application/
├──────────────────────────────────────────────┤
│   DOMAIN                                     │  <- domain/  ← heart of the system
│  · shared  · business  · customers           │
│  · catalog · resources · availability        │
│  · reservations · orders  · fulfillment      │
├──────────────────────────────────────────────┤
│   Infrastructure (adapters: DB, HTTP, etc.)  │  <- infrastructure/
└──────────────────────────────────────────────┘
           ▲
           │ verticals/<sector>/  SOLO dependen de application/domain
```

### Dirección permitida de dependencias

| Desde ↓ \ Hacia → | domain | application | infrastructure | api | verticals |
|---|---|---|---|---|---|
| **domain** | ✅ dentro del módulo | ❌ NUNCA | ❌ NUNCA | ❌ NUNCA | ❌ NUNCA |
| **application** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **infrastructure** | ✅ | ✅ | ✅ | ❌ | ❌ |
| **api** | ❌ | ✅ | ✅ | ✅ | ❌ |
| **verticals** | ✅ | ✅ | ✅ | ✅ | ✅ dentro del sector |

### Dependencias externas PROHIBIDAS al dominio

- `domain` **no depende de** infrastructure / api / FastAPI / Starlette
- `domain` **no depende de** SQLAlchemy / Alembic / Psycopg / Asyncpg
- `domain` **no depende de** ninguna base de datos, fichero o conexión de red
- `domain` **no depende de** Redis / Celery / Kafka / Firebase / Stripe / LLM
- `domain` **no menciona nombres sectoriales** (pica pollo, restaurante, etc.)

Estas reglas son verificadas por tests arquitectónicos en
`tests/architecture/test_architecture_boundaries.py` (AT-1…AT-9).

## Multi-tenancy (ADR-002)

Jerarquía conceptual: **Tenant → Business → Location**.

- `Tenant` = **límite superior de aislamiento SaaS** (NO sinónimo de persona jurídica).
- `Business` = unidad operativa dentro de un Tenant.
- `Location` = establecimiento físico o lógico dentro de un Business.

**Aislamiento:** todas las entidades operacionales llevan `tenant_id` (redundancia
intencional para filtros de aislamiento sin JOINs). Las queries de repositorio
siempre reciben `tenant_id` como parámetro explícito (keyword-only cuando
aplique).

**Repository Ports — tenancy explícita (AT-9):** ninguna operación de lectura,
listado, búsqueda, modificación o borrado sobre entidades *tenant-scoped*
puede invocarse sin `tenant_id` en la firma del Protocol.

- Excepción documentada: `ITenantRepository` (todos sus métodos) no es
  tenant-scoped; gestiona el propio límite superior SaaS.
- Entidades subordinadas a Business / Location (`Location`, `Customer`,
  `Resource`, …) añaden además `business_id` y/o `location_id` cuando el
  contexto es necesario para garantizar el boundary.

Matriz de tenancy (resumen):

| Entidad | tenant_id | business_id | location_id |
|---|---|---|---|
| Tenant | PK | N/A | N/A |
| Business | ✅ obligatorio | PK | N/A |
| Location | ✅ obligatorio | ✅ obligatorio | PK |
| Customer | ✅ obligatorio | ✅ obligatorio | ⚠️ opcional (NO identidad) |
| Resource | ✅ obligatorio | ✅ obligatorio | ✅ obligatorio |
| Order / Reservation / Fulfillment | ✅ obligatorio | ✅ obligatorio | ✅ obligatorio |

## Value objects clave
- **IDs fuertes**: wrappers dataclass inmutables sobre UUID (`TenantId`, `OrderId`,…).
- **Currency** (ISO-4217-like, sin whitelist): frozen dataclass con código 3
  letras alfabéticas, normalización a uppercase, inmutable y hashable. El
  Universal Business Core acepta cualquier código 3 letras (USD, EUR, DOP,
  JPY, MXN, GBP, CHF, COP, ARS, …) sin lista cerrada; el host podrá validar
  contra el catálogo ISO-4217 completo como extensión futura.
- **Money**: `Decimal` + `Currency` (VO). Precisión 10 / escala 4; rounding
  `ROUND_HALF_EVEN` determinista. NO float; solo acepta `int | Decimal | str`
  decimal seguro. Operaciones permitidas únicamente entre la misma moneda.
- **Temporal**: `DateRange` / `TimeRange`. Guardia `require_aware()` que
  bloquea cualquier `datetime` naive (`tzinfo=None`) en la frontera del dominio.
- **Estados**: cada módulo define sus propios `XxxStatus(Enum)`; la utilidad
  genérica `StatusTransition(Generic[S])` valida la matriz de transiciones.

## Domain Events (ADR-004)
- `DomainEvent` base: `event_id`, `occurred_at` (aware), `aggregate_id`, `aggregate_type`.
- Campos opcionales cuando proceden: `tenant_id`, `business_id`, `location_id`, `metadata`.
- **Inmutabilidad semántica de metadata:** `DomainEvent` es frozen dataclass, y
  su `metadata` se construye mediante copia defensiva convertida a
  `types.MappingProxyType`, de modo que `event.metadata["x"] = v` falla y el
  dict original pasado al constructor, si se modifica después, NO afecta al evento.
- Los agregados recolectan eventos (`AggregateRootMixin`) pero **NO los envían**.
- Dispatcher + tabla Outbox físico → FASE 2/3 (fuera de la Entrega 0.1).

## Application Layer (Gate 0.2, ADR-008, ADR-009)

La capa de Application **orquesta** casos de uso sin introducir lógica de
dominio ni acoplarse a infraestructura. Definida en `src/universal_business/application/`.

### Contracts semánticos
- **Command / Query (frozen dataclass, kw_only):** marcadores inmutables de input.
  Command muta estado; Query lee estado. No son CQRS complejo; solo semántica.
- **Handlers Protocol genéricos:**
  - `CommandHandler[CommandT, ResultT]` (varianza: C → contravariant, R → covariant).
  - `QueryHandler[QueryT, ResultT]`.
  - `DomainEventHandler[EventT]` (handlers síncronos internos, post-commit).
  - `UseCaseHandler[InT, OutT]` (handle → `tuple[OutT, Sequence[DomainEvent]]`).

### UnitOfWork Port (ADR-008 — frontera transaccional lógica)
- Protocol con `__enter__`, `__exit__`, `commit()`, `rollback()`.
- **Sin commit implícito en `__exit__`:** olvidar `commit()` → rollback automático (fail fast).
- `commit()` falla → sin commit, rollback propagado, 0 eventos post-commit.
- `handler.handle()` lanza excepción → rollback + 0 eventos.

### Idempotency (tenant-aware)
- `IdempotencyKey` VO frozen: regex `^[A-Za-z0-9_-]{8,128}$` (compatible con HTTP header `Idempotency-Key`).
- `IdempotencyStore` Protocol: `get`, `reserve`, `complete`.
- **`tenant_id` posicional-only (`/`)** en los 3 métodos (nunca implícito / contextvars).
- FSM conceptual: FREE → RESERVED → DONE.

### Eventos: Dispatcher (interno) vs Publisher (externo) — ADR-009
- **`DomainEventDispatcher`:**
  - Registro explícito `register(EventType, handler)`.
  - Orden determinista: orden de registro + resolución MRO (más específico a genérico).
  - `dispatch_many(events)`: eager validate → todos los elementos son `DomainEvent`
    ANTES de llamar a ningún handler (si hay 1 inválido, 0 handlers procesados).
  - Excepción de handler → propagación inmediata (aborta dispatch).
- **`EventPublisher` (Port):**
  - `publish(event)` / `publish_many(events)` (default iterate publish).
  - Para futuros: Outbox físico, Kafka, Rabbit, webhooks (nunca nombrados en core).

### Execution pattern
- Helper `execute_use_case` (kwargs-only): encapsula flujo canónico ADR-008:
  1. entrar en UoW → 2. `handler.handle(input)` → 3. `uow.commit()` → 4. salir UoW →
  5. post-commit: `dispatcher.dispatch_many` → 6. `publisher.publish_many` → 7. return result.
- Los casos de uso futuros deben usar este helper (o reimplementar el mismo flujo
  explícitamente) para mantener coherencia de TX/eventos.

### Vertical Extensions (ADR-005)
- `VerticalExtension` Protocol: `name: str` property + `register(context: VerticalRegistry)`.
- `VerticalRegistry`: `register(ext)` idempotente por nombre + sorted/names + metadata dict.
- Dirección de dependencia: `vertical → application` (el core no conoce vertical; la extensión se registra a sí misma).

### Errores aplicación
- `ApplicationError(Exception)` (base).
- `HandlerNotFoundError(ApplicationError)`.
- `IdempotencyConflictError(ApplicationError)`.

### Guardias arquitectónicas para Application (nuevos AT Gate 0.2)
- **AT-11**: Application ⊬ API.
- **AT-12**: Application ⊬ verticals concreto.
- **AT-13**: Application ⊬ 34 frameworks/SDK prohibidos (web, ORM, DB, brokers, AI, pagos, push, frontend, DI).
- **AT-17**: UnitOfWork, IdempotencyStore, EventPublisher son Protocol/ABC; sin implementaciones concretas dentro de `application/**`.

## Ports & Adapters
- Los contratos de repositorio son `typing.Protocol` y viven **cerca del dominio propietario**:
  - `domain/business/ports.py`
  - `domain/customers/ports.py`
  - `domain/catalog/ports.py`
  - … etc.
- **No existe** `application/ports/repositories.py` como punto central
  reexportador (evita acoplamiento global).
- Las implementaciones concretas viven en `infrastructure/` — TBD en fases posteriores.

## Extensiones verticales (ADR-005 / Regla de Oro)
- `verticals/<sector>/` solo añade **Config → Datos semilla → Extensiones específicas**.
- **Dirección única**: `vertical → application → domain`. Nada en el core conoce los
  nombres o las reglas de un vertical.
- Violación detectada por el test arquitectónico AT-6 (grep de nombres prohibidos).

## Tipado estricto
- `mypy` configurado en modo `strict=true` GLOBAL para todo `src/` (47 módulos fuente).
- **No hay overrides laxos** por módulo (`strict = false` desactivado en todos los
  esqueletos).
- Se prohíbe `# type: ignore` injustificado y `Any` indiscriminado; se prefiere
  tipado explícito.
- Matriz herramientas: `pytest` → `ruff check` → `ruff format --check` → `mypy src`.

## CI / Protección de rama permanente (GitHub Actions)
El workflow `.github/workflows/ci.yml` se ejecuta obligatoriamente en:

- `push` a `master` (protección permanente) y a `feat/architectural-baseline`.
- `pull_request` dirigido contra `master`.

Matriz: Python 3.11 y 3.12 (sin servicios de DB / Docker / publicación; solo
calidad de código).

## Alcance — Entrega 0.1 Architectural Baseline (scope REAL, histórico)

| Capa | Qué se entrega (RC1) | Qué NO se entrega (FASE ≥0.2) |
|---|---|---|
| **domain.shared** | `Money` + `Currency` sin whitelist; IDs fuertes; `DateRange`/`TimeRange` UTC-aware; `StatusTransition`; `AggregateRootMixin`; `DomainEvent.metadata` inmutable; errores fuertemente tipados | Catálogo ISO-4217 completo (extensión futura) |
| **domain.business** | `Tenant`/`Business`/`Location` + `BusinessSettings`; repos `ITenantRepository`, `IBusinessRepository`, `ILocationRepository` con tenancy explícita | Jerarquías multinivel avanzadas; jerarquía organizativa extendida |
| **domain.customers** | `Customer` con external_ref opcional; `ICustomerRepository.get(tenant_id,business_id,customer_id)` | CRM; scoring; segmentación; programas de fidelidad |
| **domain.catalog** | Entidad mínima `CatalogItem` (identidad, tenancy, status, nombre, precio Money placeholder, activo). Contratos `ICatalogRepository` con tenancy explícita | Pricing avanzado; SKU; variantes; atributos multivalor; stock real |
| **domain.resources** | Entidad mínima `Resource` (identidad, tenancy, name, status, tipo, capacidad). `IResourceRepository` con location_id | Agendas; pools; dependencias; capacity planners |
| **domain.availability** | Entidades mínimas `AvailabilityRule`/`AvailabilityBlock`; ports con `list_rules_for_resource(tenant_id,location_id)`. Invariantes de construcción triviales | Motor de disponibilidad; solapamientos; reglas complejas; scheduling |
| **domain.reservations** | Entidad mínima `Reservation` (identidad, tenancy, customer_id, timespan, status). Ports tenancy explícita | Cancelaciones; rebooking; prioridad; waitlist; políticas de no-show |
| **domain.orders** | Entidad mínima `Order` (identidad, tenancy, customer_id, totals Money placeholder, status). Ports tenancy explícita | Líneas de pedido; impuestos; descuentos; ciclo de vida completo |
| **domain.fulfillment** | Entidad mínima `Fulfillment` (identidad, tenancy, order_id/reservation_id opcionales, tipo, status). Ports | Asignación; routing; tracking; SLA; fulfillment operacional |
| **application** | Solo estructura de paquete (`__init__.py`) | Use cases completos, CQRS, UnitOfWork |
| **infrastructure** | Solo estructura. Nada de implementación | ORM / repositorios / DB / brokers / Outbox físico |
| **api** | Solo estructura | FastAPI / endpoints / Pydantic |
| **verticals** | Solo estructura (vacío) | Cualquier vertical, incluyendo pica-pollo |
| **tests** | Unitarios VOs + entidades; arquitectura AT-1..AT-9 (nuevo AT-9: ports tenancy signatures); importación subprocess sin externos; tests específicos Currency y metadata inmutable | Tests de integración / E2E |
| **tooling** | `pyproject.toml`: pytest, ruff, mypy strict. CI en `master` y `feat/*`. `[docs]` extra opcional para `fpdf2` (NUNCA runtime dep) | Bandit, pre-commit (opcional), Docker, Postgres service, releases, PyPI publication

---

## Alcance — Entrega 0.2 Foundation / Application Layer (scope REAL)

| Capa | Qué se entrega (Gate 0.2) | Qué NO se entrega (FASE ≥0.3) |
|---|---|---|
| **application.messaging** | `Command` / `Query` frozen dataclass kw_only; `CommandHandler[C,R]` / `QueryHandler[Q,R]` Protocol genérico @runtime_checkable | Buses CQRS sofisticados; registries globales; service locator; reflexión compleja |
| **application (errors)** | `ApplicationError`, `HandlerNotFoundError`, `IdempotencyConflictError` (jerarquía mínima) | Result/Either monads |
| **application (UnitOfWork)** | `UnitOfWork` Protocol: `__enter__`/`__exit__`/`commit()`/`rollback()`. Semántica: **sin commit implícito en __exit__** (ADR-008). | Implementación SQLAlchemy / DB de UnitOfWork |
| **application (Idempotency)** | `IdempotencyKey` VO frozen + regex validado; `IdempotencyStore` Protocol con `get`/`reserve`/`complete` y **tenant_id posicional-only** obligatorio | Redis / tabla de idempotencia física |
| **application.events (Dispatcher)** | `DomainEventHandler[E]` Protocol; `DomainEventDispatcher` registro explícito ordenado, resolución MRO, `dispatch_many` eager validate, excepción propagada (ADR-009) | Autodiscovery / decorador @handler global; bus asíncrono |
| **application.events (Publisher)** | `EventPublisher` Protocol `publish`/`publish_many` (default iterate publish) | Outbox físico; Kafka / RabbitMQ / webhooks adapter |
| **application.execution** | `UseCaseHandler[In,Out]` Protocol (tuple[Out, Sequence[DomainEvent]]); helper `execute_use_case` kwargs-only encapsula ADR-008 flujo canónico | Casos de uso concretos (CreateOrder, CreateReservation…) |
| **application.extensions** | `VerticalExtension` Protocol; `VerticalRegistry` dataclass idempotente por nombre, sorted/names/metadata | Cualquier implementación de vertical concreto |
| **domain (todos los módulos)** | **INTACTO 0.1 (sin cambios)** | |
| **infrastructure** | Solo estructura `__init__.py` — sin cambios | ORM / repositorios / DB / brokers / Outbox físico / UnitOfWork concreto |
| **api** | Solo estructura `__init__.py` — sin cambios | FastAPI / Starlette / endpoints / Pydantic |
| **verticals** | Solo estructura `__init__.py` — sin cambios | Cualquier vertical, incluyendo pica-pollo |
| **tests AT nuevos** | AT-11 (App⊬API), AT-12 (App⊬Verticals), AT-13 (App sin frameworks/SDK), AT-17 (Ports son abstracciones Protocol/ABC). AT-1..AT-9 intactos. | |
| **tests unit nuevos** | 6 suites: messaging / UoW / idempotency / events / usecase / verticals (~95 tests). Fake doubles manuales dentro de tests (no en src) | Tests de integración / E2E / DB real |
| **docs** | DEVELOPMENT_STATUS.md actualizado Gate 0.2; ADR-008 TX semantics; ADR-009 dispatch/publish semantics; plan_entrega_0.2_foundation.md; sección Application ARCHITECTURE.md | PDF generación automática (no pedida en Gate 0.2) |
| **tooling** | `pyproject.toml` SIN CAMBIOS. Runtime `dependencies = []` permanece. Versiones cerradas dev tooling intactas: `pytest>=8,<9`, `ruff>=0.15,<0.16`, `mypy>=2.1,<3` | Añadir runtime deps (FastAPI/SQLAlchemy/etc.) |
| **versión paquete** | `0.2.0` (`universal_business.__version__`) | |

## Enlaces
- `docs/adr/ADR-001.md` … `docs/adr/ADR-009.md` — decisiones vinculantes.
- `docs/plan_entrega_0.1_architectural_baseline.md` — plan detallado + Gate 0.1.
- `docs/plan_entrega_0.2_foundation.md` — plan detallado + Gate 0.2.
