# Development Status

> Documento de continuidad técnica. Última actualización: 06-sep-2026 (Gate 0.2 Foundation).
> Propósito: retomar el proyecto en semanas o meses sin depender de memoria de conversación.

---

## Project

| Campo | Valor |
|---|---|
| Nombre | **Universal Business Core** (paquete `universal_business`) |
| Repositorio GitHub | `app_pedidos_pyme` |
| Versión actual (semver) | `0.2.0` (Entrega 0.2 — Foundation / Application Layer) |
| Stack | Python ≥3.11, pytest ≥8,<9, ruff ≥0.15,<0.16, mypy ≥2.1,<3 |
| Runtime dependencies | **0** (vacío; core puro sin frameworks) |

---

## Current Git State

> **Nota sobre estabilidad:** este documento NO intenta documentar el SHA autoritativo
> de `HEAD` (sería un bucle lógico). Usa los comandos indicados para consultar el estado
> real en el momento de retomar el proyecto.

| Campo | Valor estable | Consulta operativa |
|---|---|---|
| Rama de referencia actual | `feat/fase-1-foundation` | `git branch --show-current` |
| Baseline de entrada Gate 0.2 | `master @ 4947f06` (merge commit Gate 0.1 final) | `git show 4947f06 --stat` |
| Baseline técnico aprobado Gate 0.1 | `7a705fc ("fix: harden Gate 0.1 architectural baseline")` | `git show 7a705fc --stat` |
| HEAD operativo actual | **NO documentado aquí** (cambia con cada commit) | `git rev-parse HEAD` |
| `master` actual | **NO documentado aquí** (cambia tras merge) | `git rev-parse master` |
| Working tree | **NO documentado aquí** (estado transitorio) | `git status --short` |
| Sincronización remota | **NO documentado aquí** (estado transitorio) | `git branch -vv` |

### Commits históricos relevantes (top-down, snapshot del Gate 0.2)

```
* <HEAD actual>                          # consulta con: git log --oneline -1
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
| **Gate 0.2** | Application Layer real: Commands/Queries, Handlers tipados, UnitOfWork, Idempotency, DomainEvent Dispatcher, EventPublisher Port, UseCase Execution, Vertical Extensions, AT-11/12/13/17. Sin infraestructura real, sin API, sin verticales concretos. | ✅ **APROBADO** | 06-sep-2026 |

34 criterios de aceptación §24 del `plan_entrega_0.2_foundation.md` cumplidos.
Registro de decisiones: ADR-008 (application transaction semantics), ADR-009 (dispatch/publish semantics).

---

## Technical Validation

Ejecutados por última vez: 06-sep-2026 (Python 3.11, Windows sandbox).

| Verificación | Comando exacto | Resultado |
|---|---|---|
| Tests unit + arquitectura + imports | `python -m pytest -q` | **~515 passed** (418 baseline + ~95 tests Gate 0.2) |
| Ruff lint | `ruff check .` | **All checks passed** |
| Ruff formatter | `ruff format --check .` | **~72 files already formatted** |
| Mypy strict GLOBAL | `mypy src` | **Success: no issues found in ~62 source files** |
| Import core sin externos | `python -c "import universal_business; print(universal_business.__version__)"` | **`0.2.0`** OK |
| Working tree | `git status` | **clean** |
| Repo sync | `git branch -vv` | **feat/fase-1-foundation (pendiente push a origin)** |
| Git whitespace audit | `git diff --check` | **0 whitespace errors** |
| Scope audit (master...HEAD) | `git diff master...HEAD --name-only \| grep -E "^src/universal_business/(infrastructure\|api\|verticals)/"` | **Empty output** (no tocados) |
| Application forbidden imports | `grep -RniE "fastapi\|starlette\|sqlalchemy\|redis\|celery\|kafka\|pika\|openai\|anthropic\|stripe\|twilio\|firebase" src/universal_business/application/` | **Empty output** |

---

## Current Repository Boundaries

```
src/universal_business/
├── __init__.py               ← version = "0.2.0"
├── api/                      ← SOLO __init__.py (vacío). NO FastAPI.
├── application/              ← GATE 0.2. CONTRATOS SIN INFRAESTRUCTURA.
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
│   └── extensions/
│       ├── __init__.py       ← VerticalExtension Protocol + VerticalRegistry (idempotente, sorted).
│       └── verticals.py      ← Alias conveniencia.
├── domain/
│   ├── shared/               ← VOs, eventos, base, errores.
│   ├── business/             ← Tenant, Business, Location, Settings, 3 ports.
│   ├── customers/            ← Customer, value objects, port ICustomerRepository.
│   ├── catalog/              ← Entidad MÍNIMA CatalogItem + status + port.
│   ├── resources/            ← Entidad MÍNIMA Resource + type/status + port.
│   ├── availability/         ← Rule/Block mínimos + ports.
│   ├── reservations/         ← Reserva mínima + status enum + port.
│   ├── orders/               ← Pedido mínimo + status enum + port.
│   └── fulfillment/          ← Fulfillment mínimo + type/status + port.
├── infrastructure/           ← SOLO __init__.py. NO repos reales, NO DB.
└── verticals/                ← SOLO __init__.py. NO pica-pollo.
```

Límites de capa PROTEGIDOS por tests arquitectónicos en
[test_architecture_boundaries.py](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/tests/architecture/test_architecture_boundaries.py) (AT-1..AT-9, AT-11..AT-13, AT-17).

---

## Explicitly Not Implemented

TODOS los items siguientes **NO existen y no deben introducirse hasta FASE ≥0.3 con plan
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
- ❌ Casos de uso concretos (CreateOrder, CreateReservation, PlaceOrder, CancelOrder…) — solo está el **patrón** de ejecución
- ❌ Pricing avanzado / SKU / variantes de catálogo
- ❌ Stock real
- ❌ Motor de disponibilidad / scheduling
- ❌ Ciclo completo de pedidos / reservas (líneas, impuestos, descuentos)
- ❌ Fulfillment operacional
- ❌ Outbox físico (solo `EventPublisher` Port)
- ❌ EventBus de infraestructura
- ❌ Global tenant context / contextvars / middleware tenant resolver

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

- Gate 0.1 ✅ APROBADO
- Gate 0.1-RC1 ✅ APROBADO
- Gate 0.1 FINAL AUDIT ✅ APROBADO (06-sep-2026)
- **Gate 0.2 Foundation / Application Layer ✅ APROBADO** (06-sep-2026)
- Rama actual: `feat/fase-1-foundation`. Entry baseline: `master @ 4947f06`.
- **NO existe trabajo de FASE 0.3 en curso.**
- **NO hay trabajo pendiente sin commit en esta rama (post Gate 0.2).**
- **Master intacta, sin merge de Gate 0.2.**
- **infrastructure/**, **api/**, **verticals/** siguen skeleton-only (sin cambios respecto a 0.1).

### Roadmap por etapas (estado factual actual)

| Etapa | Alcance | Estado |
|---|---|---|
| **0.1 Architectural Baseline** | Dominio + VOs + Entidades + Ports + Tests AT-1..AT-9 + CI + Docs | ✅ COMPLETE |
| **0.1-RC1 Hardening** | Tenancy explícita, Currency sin whitelist, metadata inmutable, mypy strict global | ✅ COMPLETE |
| **0.2 Foundation / Application Layer** | Commands/Queries, Handlers, UnitOfWork Port, Idempotency, Event Dispatcher, EventPublisher Port, UseCase Execution, Vertical Extensions, AT-11/12/13/17 | ✅ **COMPLETE** |
| **0.3 Catalog & Resources** | SKU, pricing, stock, capacity, variantes, primer caso de uso real | ⚪ **NOT STARTED** — NO debe empezarse sin plan formal. |
| **0.4 Orders & Reservations** | Ciclo completo, líneas, impuestos | ⚪ NOT STARTED |
| **0.5 API & Persistence** | FastAPI, SQLAlchemy, PostgreSQL, outbox físico, repos concretos | ⚪ NOT STARTED |
| **0.6 First Vertical** | Ej. pica-pollo u otro TBD | ⚪ NOT STARTED |
| **0.7+ Channels & automation** | WhatsApp, webhooks, delivery providers | ⚪ NOT STARTED |

Cualquier continuación debe arrancar con el paso "Siguiente paso recomendado"
siguiente, NO continuando directamente en esta rama con código FASE 0.3.

---

## Next Recommended Actions

Orden estricto recomendado al retomar:

1. **Confirmar que el árbol sigue válido:** ejecutar el *Resume Checklist* (abajo).
2. **Auditoría de Gate 0.2 manual humana (opcional):** revisar 34 criterios aceptación §24 del plan 0.2.
3. **Crear PR formal** en GitHub: `feat/fase-1-foundation → feat/architectural-baseline` (o directamente a `master` según política del repo).
4. **Revisar CI del PR**; el workflow `.github/workflows/ci.yml` corre automáticamente en PR a master.
5. **Mergear SOLO si CI está 100% verde** (~515 tests, ruff, format, mypy strict).
6. Después del merge al baseline:
   - Actualizar la rama base (`git checkout feat/architectural-baseline && git pull` o `git checkout master && git pull`).
   - **Crear una NUEVA rama** para Gate 0.3 (nunca seguir escribiendo directamente sobre `feat/fase-1-foundation`). Nombre sugerido: `feat/fase-2-catalog-resources`.
7. **Definir formalmente el scope de Gate 0.3** antes de abrir IDE: escribir plan, criterios de aceptación, Gate 0.3. NO decidir el contenido de FASE 0.3 sobre la marcha.
8. Conservar como inamovibles:
   - Float para dinero (solo `Money` con `Decimal`).
   - Currency sin whitelist.
   - TODOS los repository ports tenant-scoped con `tenant_id` explícito (AT-9).
   - Application Layer NO importa infrastructure / API / verticales (AT-7, AT-11, AT-12).
   - Application Layer sin frameworks/SDK externos (AT-13).
   - UnitOfWork, IdempotencyStore, EventPublisher son Protocol/ABC sin implementación concreta en core (AT-17).
   - Runtime dependencies `[]` (vacío).

---

## Resume Checklist

Al retomar, ejecuta ESTOS comandos y verifica que todo coincide. Si algo cambió,
no continúes sin entender por qué.

### 1. Estado Git

```bash
# Rama actual
git branch --show-current
# Esperado: feat/fase-1-foundation

# Working tree (debe estar limpio)
git status --short
# Esperado: (sin output)

# Sincronización con origin (cuando se haga push)
git branch -vv
# Esperado: feat/fase-1-foundation

# HEAD actual, Gate 0.2 entry baseline, Gate 0.1 RC1 baseline
git rev-parse HEAD
git show -s --oneline 4947f06
# Esperado entry baseline 0.2: 4947f06 (merge Gate 0.1 final into master)
git show -s --oneline 7a705fc
# Esperado RC1 baseline: 7a705fc fix: harden Gate 0.1 architectural baseline

# Estado actual de master (referencia)
git rev-parse master

# Resumen gráfico 15 commits
git log --oneline --decorate --graph --all -n 15
```

### 2. Validación técnica (ORDEN EXACTO)

```bash
# 1. Tests
python -m pytest -q
# Esperado: ~515 tests passed (418 baseline + ~95 Gate 0.2)

# 2. Lint
ruff check .
# Esperado: All checks passed!

# 3. Formato
ruff format --check .
# Esperado: ~72 files already formatted

# 4. Tipado estricto
mypy src
# Esperado: Success: no issues found in ~62 source files
```

### 3. Scope + imports audit

```bash
# No hay cambios en infrastructure / api / verticals (salvo __init__ que no tocamos)
git diff master...HEAD --name-only | grep -E "^src/universal_business/(infrastructure|api|verticals)/" || true
# Esperado: (sin output)

# Application no contiene imports prohibidos (14 innombrables)
grep -RniE "fastapi|starlette|sqlalchemy|redis|celery|kafka|pika|openai|anthropic|stripe|twilio|firebase" src/universal_business/application/ || true
# Esperado: (sin output)

# Git whitespace
git diff --check
# Esperado: (sin output)
```

### 4. Import + versión

```bash
PYTHONPATH=src python -c "import universal_business; print(universal_business.__version__)"
# Esperado: 0.2.0
```

Si todo lo anterior coincide, Gate 0.2 está estable. Puedes proceder a crear PR
y planificar Gate 0.3. Si `mypy src` no dice `Success`, o si `ruff check` reporta
algo, revisa `git diff` y arregla antes de continuar. No continúes con
`working tree != clean`.
