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
`tests/architecture/test_architecture_boundaries.py` (AT-1…AT-8).

## Multi-tenancy (ADR-002)

Jerarquía conceptual: **Tenant → Business → Location**.

- `Tenant` = **límite superior de aislamiento SaaS** (NO sinónimo de persona jurídica).
- `Business` = unidad operativa dentro de un Tenant.
- `Location` = establecimiento físico o lógico dentro de un Business.

**Aislamiento:** todas las entidades operacionales llevan `tenant_id` (redundancia
intencional para filtros de aislamiento sin JOINs). Las queries de repositorio
siempre reciben `tenant_id` como primer parámetro.

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
- **Money**: `Decimal` + moneda ISO-4217. Escala 4 decimales; rounding
  `ROUND_HALF_EVEN`. NO float; operaciones `int | Decimal | str`. Monedas
  permitidas en whitelist.
- **Temporal**: `DateRange` / `TimeRange`. Guardia `require_aware()` que
  bloquea cualquier `datetime` naive (`tzinfo=None`) en la frontera del dominio.
- **Estados**: cada módulo define sus propios `XxxStatus(Enum)`; la utilidad
  genérica `StatusTransition(Generic[S])` valida la matriz de transiciones.

## Domain Events (ADR-004)
- `DomainEvent` base: `event_id`, `occurred_at` (aware), `aggregate_id`, `aggregate_type`.
- Campos opcionales cuando proceden: `tenant_id`, `business_id`, `location_id`, `metadata`.
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

## Alcance — Entrega 0.1 Architectural Baseline

| Capa | Qué se entrega | Qué NO se entrega |
|---|---|---|
| **domain** | VOs compartidos; Tenant / Business / Location / Customer; módulos esqueleto con entidades + status + ports Protocol | Pricing / stock / motor disponibilidad / reglas pedidos/reservas |
| **application** | Solo estructura de paquete (`__init__.py`) | Use cases completos, CQRS, UnitOfWork |
| **infrastructure** | Solo estructura. Nada de implementación | ORM / repositorios / DB / brokers |
| **api** | Solo estructura | FastAPI / endpoints / Pydantic |
| **verticals** | Solo estructura (vacío) | Cualquier vertical, incluyendo pica-pollo |
| **tests** | unitarios VOs + entidades; arquitectura AT-1..AT-8; importación subprocess | tests de integración / E2E |
| **tooling** | pyproject.toml: pytest, ruff, mypy. CI GitHub Actions | Bandit, pre-commit (opcional) |

## Enlaces
- `docs/adr/ADR-001.md` … `docs/adr/ADR-007.md` — decisiones vinculantes.
- `docs/plan_entrega_0.1_architectural_baseline.md` — plan detallado + Gate 0.1.
