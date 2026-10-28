# Universal Business Core

> Motor backend empresarial **universal y agnóstico**, diseñado para reutilizarse en múltiples verticales de negocio sin necesidad de reescribir el núcleo.

**Paquete Python:** `universal_business` · **Versión:** `0.3.0` · **Estado:** Gate 0.3 Catalog & Resources integrado ✅

---

## ¿Qué es Universal Business Core?

**No es una app específica de restaurante.** No está ligado a ningún sector concreto.

Es un **núcleo de negocio reusable** que abstrae conceptos comunes a la mayoría de
pequeñas y medianas empresas:

- Tenencia de locales y unidades de negocio.
- Gestión de clientes.
- Catálogo de productos/servicios.
- Recursos y disponibilidad horaria.
- Reservas y citas.
- Pedidos y su ciclo de vida.
- Cumplimiento / fulfillment.

El *"pica-pollo"* (pollos a la brasa, delivery, etc.) está considerado **como
primera vertical de ejemplo FUTURA**, pero **NO existe implementación actual**.
El core mismo no contiene ninguna regla específica de comida rápida, restaurantes,
o cualquier otro sector particular.

---

## Objetivos

| Objetivo | Descripción |
|---|---|
| **Backend universal** | Un solo núcleo sirve para múltiples sectores. |
| **Multi-tenant SaaS-ready** | Aislamiento lógico estricto por `tenant_id`. |
| **Monolito modular** | Arquitectura mantenible a escala humana; sin microservicios prematuros. |
| **Dominio independiente** | Sin acoplamiento a frameworks de infraestructura. |
| **Preparado para verticales** | Extensiones desacopladas (`verticals/`) inyectan reglas de negocio concretas. |
| **Altamente testeable** | Core 100% offline-testable, sin servicios externos en Entrega 0.1. |
| **Extensible** | Cualquier capa puede reemplazarse por implementaciones concretas sin tocar el dominio. |

---

## Arquitectura

```
┌──────────────────────────────────┐
│   API / Channels     (⏳ FASE 2) │  ← Entrada externa: REST, GraphQL, Webhook...
└──────────────┬───────────────────┘
               │
┌──────────────▼───────────────────┐
│   Application        (✅ 0.2–0.3) │  ← Casos de uso / commands / queries
└──────────────┬───────────────────┘
               │
┌──────────────▼───────────────────┐
│              Domain              │  ← ✅ 0.1–0.3 IMPLEMENTADO
│  shared · business · customers   │
│  catalog · resources · avail.    │
│  reservations · orders · full.   │
│  ⚑ Ports (Protocols, NO impl.)  │
└──────────────┬───────────────────┘
               │
┌──────────────▼───────────────────┐
│   Infrastructure   (⏳ FASE 2)   │  ← ORM / DB / brokers / clientes externos
└──────────────────────────────────┘

      verticals/  ──►  dependen HACIA DENTRO (contratos 0.2; implementación futura)
                      NUNCA al revés. El core NO conoce los verticales.
```

- **DDD + Ports & Adapters:** los repositorios se definen como `typing.Protocol` cerca de su
  entidad; las implementaciones físicas pertenecen a Infrastructure.
- **Dominio agnóstico protegido** por tests arquitectónicos AT-1..AT-9 que impiden fugas de
  infraestructura o nombres de verticales.
- **Regla de oro:** "Si una regla solo tiene sentido para un negocio concreto, NO pertenece al core."

---

## Módulos de dominio

La tabla siguiente conserva el alcance de la entrega 0.1; desde 0.3, catálogo y recursos incluyen `Offering`, categorías, requisitos de recursos, `ResourceType` y `Resource`, con casos de uso en la capa de aplicación.

| Módulo | Estado 0.1 | Propósito |
|---|---|---|
| **`shared`** | ✅ Completo | Value Objects base: `Money`/`Currency`, IDs fuertes, `DateRange`/`TimeRange`, `StatusTransition`, `AggregateRootMixin`, `DomainEvent` con metadata inmutable, errores fuertemente tipados. |
| **`business`** | ✅ Completo | Entidades `Tenant`, `Business`, `Location`. `BusinessSettings`. Tres repositorios Protocol. Jerarquía multi-tenant. |
| **`customers`** | ✅ Completo | Entidad `Customer` con `external_ref` opcional. Tipos de documento. Repositorio con tenancy explícita. |
| **`catalog`** | 🟢 Contrato mínimo | Entidad `CatalogItem` (identidad, nombre, status, precio placeholder, activo). Ports Protocol. Sin pricing avanzado. |
| **`resources`** | 🟢 Contrato mínimo | Entidad `Resource` (tipo, capacidad, location). Ports Protocol. Sin agendas. |
| **`availability`** | 🟢 Contrato mínimo | Entidades `AvailabilityRule` / `AvailabilityBlock` mínimas. Ports. Sin motor de disponibilidad. |
| **`reservations`** | 🟢 Contrato mínimo | `Reservation` (cliente, rango temporal, estado). `ReservationStatus` enum. Ports. Sin waitlist ni políticas. |
| **`orders`** | 🟢 Contrato mínimo | `OrderStatus` (9 estados), `Order` mínima (totales placeholder). Ports. Sin líneas, impuestos ni descuentos. |
| **`fulfillment`** | 🟢 Contrato mínimo | `FulfillmentStatus`, `FulfillmentType`, `Fulfillment` mínima vinculada a pedido/reserva. Ports. Sin tracking. |

---

## Multi-tenancy

Jerarquía SaaS de aislamiento lógico:

```
Tenant  ────  (boundary superior, NO necesariamente persona jurídica)
   │
   └── Business  ──  unidad operativa (sucursal, marca, marca subsidiaria)
           │
           └── Location  ──  establecimiento físico o lógico (local, warehouse, zona).
```

- **Toda entidad operacional lleva `tenant_id` explícito** (redundancia intencional para
  filtros de aislamiento sin JOINs).
- **Repository ports tenancy explícita (AT-9):** ningún método de repositorio
  tenant-scoped se invoca sin `tenant_id` en su firma; entidades subordinadas añaden
  además `business_id` / `location_id` cuando corresponde.
- Excepción documentada: `ITenantRepository` gestiona el propio límite SaaS.

---

## Estado actual

| Indicador | Valor |
|---|---|
| Gate 0.1 — Architectural Baseline | ✅ Integrado |
| Gate 0.2 — Foundation / Application Layer | ✅ Integrado |
| Gate 0.3 — Catalog & Resources | ✅ Integrado en `master` |
| Última validación documentada del hardening 0.3 | 646 pruebas superadas; ver [informe](docs/informe_hardening_0.3_execution_hooks_stateless_20260906.md) |
| CI del merge 0.3 | ✅ Python 3.11 y 3.12, pytest, Ruff y mypy |
| API, persistencia y primera vertical | ⏳ Pendientes |

La implementación actual es un núcleo backend: API, infraestructura y verticales
concretas son esqueletos. Pedidos, reservas y disponibilidad aún no tienen su
comportamiento completo.

---

## Calidad

Ejecutar siempre en este orden:

```bash
python -m pytest          # tests unit + arquitectura + imports
ruff check .              # lint
ruff format --check .     # formatter
mypy src                  # strict global typing
```

---

## Instalación para desarrollo

Requisitos previos: **Python 3.11 o 3.12**.

```bash
# 1. Crear entorno virtual
python -m venv .venv

# 2. Activar en Windows PowerShell / CMD:
#   PowerShell:   .\.venv\Scripts\Activate.ps1
#   CMD:          .venv\Scripts\activate.bat
#   Git Bash:     source .venv/Scripts/activate
#   macOS/Linux:  source .venv/bin/activate

# 3. Actualizar pip
python -m pip install --upgrade pip

# 4. Instalar core en modo editable + dev extras (pytest, ruff, mypy)
pip install -e ".[dev]"

# 5. [Opcional] Regenerar PDF del plan (fpdf2 NO es runtime dep):
pip install -e ".[docs]"
python docs/_gen_plan_pdf.py
```

---

## Documentación

| Documento | Ruta |
|---|---|
| 🏛️ Hoja de ruta del Universal Business Core (PDF autoritativo) | [`hoja_ruta_universal_business_core.pdf`](hoja_ruta_universal_business_core.pdf) |
| 📘 Arquitectura detallada + alcance 0.1 | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| 📋 Plan de entrega 0.1 Architectural Baseline (v2.1 RC1) | [`docs/plan_entrega_0.1_architectural_baseline.md`](docs/plan_entrega_0.1_architectural_baseline.md) |
| 📋 Versión PDF del plan | [`docs/plan_entrega_0.1_architectural_baseline.pdf`](docs/plan_entrega_0.1_architectural_baseline.pdf) |
| 📝 Registro de decisión arquitectónica (ADRs) | [`docs/adr/`](docs/adr/) |
| 🛑 Estado actual y punto de parada | [`docs/DEVELOPMENT_STATUS.md`](docs/DEVELOPMENT_STATUS.md) |

---

## Decisiones arquitectónicas (ADRs)

| ID | Título | Estado |
|---|---|---|
| **ADR-001** | Monolito modular vs microservicios → **Monolito modular DDD** | ✅ |
| **ADR-002** | Estrategia multi-tenant → **Aislamiento lógico por columna tenant_id** | ✅ |
| **ADR-003** | Modelo de CatalogItem → **shared Kernel, value objects estables** | ✅ |
| **ADR-004** | Domain Events + Outbox → **Mixin recolector + tabla outbox físico FASE ≥2** | ✅ |
| **ADR-005** | Extensiones verticales → **verticals/ hacia adentro, nunca al revés** | ✅ |
| **ADR-006** | Resources / Availability → **Recursos como capacidad, disponibilidad como rules+blocks** | ✅ |
| **ADR-007** | Idempotencia pedidos / reservas → **Idempotency-Key en capa aplicación** | ✅ |
| **ADR-008–010** | Transacciones, publicación de eventos y Offering universal | ✅ |

---

## Roadmap (alto nivel, sin fechas)

```
0.1  Architectural Baseline        ✅ integrado
     │
     ▼
0.2  Foundation / Core             ✅  Use cases, UnitOfWork, vertical skeleton
     │
     ▼
0.3  Catalog & Resources           ✅  Offering, categorías y recursos
     │
     ▼
0.4  Orders & Reservations         ⏳  Ciclo completo, líneas, impuestos
     │
     ▼
0.5  API & Persistence             ⏳  FastAPI, SQLAlchemy, outbox físico
     │
     ▼
0.6  First Vertical                ⏳  Vertical pica-pollo u otro TBD
     │
     ▼
0.7+ Channels & automation         ⏳  WhatsApp, webhooks, delivery providers
```

No se avanza a la siguiente etapa sin aprobación humana del Gate anterior.

---

## Principios de diseño

> 🌟 **Regla cardinal:**
> *"Si una regla solo tiene sentido para un negocio concreto, NO pertenece al core."*

- **Domain first** — el dominio dicta; la infraestructura se adapta.
- **No premature infrastructure** — sin FastAPI/SQLA en Entrega 0.1.
- **No vertical leakage** — ningún nombre o regla de sector se filtra al core.
- **Explicit tenancy** — `tenant_id` obligatorio en ports y queries.
- **Decimal for money** — `Money` con `Decimal` escala 4; Float estrictamente prohibido.
- **Timezone-aware datetimes** — `require_aware()` guardia en frontera del dominio.
- **Ports near owning domain** — repositorios Protocol cerca de su entidad; punto central de reexport prohibido.

---

## Estado de desarrollo

El punto de parada actual, la checklist para retomar en otro día, y los hitos
cumplidos están registrados en:

👉 [**`docs/DEVELOPMENT_STATUS.md`**](docs/DEVELOPMENT_STATUS.md)

---

*Universal Business Core* — trabajo temprano, ingeniería disciplinada, núcleo reusable.
