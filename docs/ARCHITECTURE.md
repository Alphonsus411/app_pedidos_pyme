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

## Alcance — Entrega 0.1 Architectural Baseline (scope REAL)

| Capa | Qué se entrega (RC1) | Qué NO se entrega (FASE 1…FASE 3) |
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

## Enlaces
- `docs/adr/ADR-001.md` … `docs/adr/ADR-007.md` — decisiones vinculantes.
- `docs/plan_entrega_0.1_architectural_baseline.md` — plan detallado + Gate 0.1.
