# PLAN DE IMPLEMENTACIÓN — ENTREGA 0.2: FOUNDATION / APPLICATION LAYER

**Documento:** Plan detallado + Criterios de aceptación Gate 0.2
**Versión:** 1.0 (final, Gate 0.2 closed)
**Fecha:** 6 de septiembre de 2026
**Branch:** `feat/fase-1-foundation`
**Baseline de entrada:** `master @ 4947f06` (merge commit Gate 0.1 final)
**Documentos de autoridad:** ADR-001..ADR-009; Gate 0.1 DEVELOPMENT_STATUS.md
**Estado:** Gate 0.2 APROBADO (34/34 criterios §24 aceptación). Espera merge humano.

---

## A. Evaluación del repositorio antes de Gate 0.2

| Elemento | Estado al inicio de 0.2 |
|---|---|
| Código Python / paquete `src/universal_business/` | ✅ 47 módulos fuente + 8 dominios + 4 capas (vacías application/api/infra/verticals) |
| `pyproject.toml` | ✅ strict=true mypy global; `[docs]` extra opcional; 0 runtime deps |
| Estructura de paquetes y módulos | ✅ monolito modular DDD (Gate 0.1) |
| Tests (`tests/`) | ✅ 418 tests (unit + arquitectura AT-1..AT-9 + imports) |
| Documentación arquitectónica | ✅ ARCHITECTURE.md; ADR-001..ADR-007 |
| CI | ✅ `.github/workflows/ci.yml` matriz 3.11/3.12 |
| Branch | ✅ `feat/fase-1-foundation` creada desde `master @ 4947f06`; master NO tocado |

---

## B. Estructura final de paquetes (Gate 0.2)

```
app_pedidos_pyme/
├── docs/
│   ├── DEVELOPMENT_STATUS.md                       ← actualizado Gate 0.2
│   ├── ARCHITECTURE.md                             ← nueva sección Application Layer
│   ├── plan_entrega_0.2_foundation.md              ← ESTE DOCUMENTO
│   └── adr/
│       ├── ADR-008-application-transaction-semantics.md   ← NUEVO (decisiones 0.2)
│       └── ADR-009-domain-event-dispatch-publish-semantics.md ← NUEVO (decisiones 0.2)
│
├── src/
│   └── universal_business/
│       ├── __init__.py                              ← version = "0.2.0"
│       ├── application/                             ← GATE 0.2 NUEVA (no vacía)
│       │   ├── __init__.py
│       │   ├── errors.py
│       │   ├── messaging/
│       │   │   ├── __init__.py
│       │   │   ├── commands.py
│       │   │   ├── queries.py
│       │   │   └── handlers.py
│       │   ├── unit_of_work.py
│       │   ├── idempotency.py
│       │   ├── events/
│       │   │   ├── __init__.py
│       │   │   ├── dispatcher.py
│       │   │   └── publisher.py
│       │   ├── execution/
│       │   │   ├── __init__.py
│       │   │   └── use_case.py
│       │   └── extensions/
│       │       ├── __init__.py
│       │       └── verticals.py
│       ├── domain/                                  ← INTACTO (sin cambios)
│       ├── api/                                     ← SOLO __init__.py (NO tocado)
│       ├── infrastructure/                          ← SOLO __init__.py (NO tocado)
│       └── verticals/                               ← SOLO __init__.py (NO tocado)
│
├── tests/
│   ├── architecture/
│   │   └── test_architecture_boundaries.py         ← NUEVOS AT-11/AT-12/AT-13/AT-17 (AT-1/AT-9 intactos)
│   └── unit/
│       ├── test_application_messaging.py           ← NUEVO (12 tests)
│       ├── test_application_uow.py                 ← NUEVO (FakeUnitOfWork + ~8 tests)
│       ├── test_application_idempotency.py         ← NUEVO (FakeIdempotencyStore + ~7 tests)
│       ├── test_application_events.py              ← NUEVO (FakeEventPublisher + ~14 tests)
│       ├── test_application_usecase.py             ← NUEVO (execute_use_case + ~12 tests)
│       └── test_application_verticals.py           ← NUEVO (VerticalRegistry + ~8 tests)
│
└── .trae/specs/gate02-foundation-application-layer/
    ├── spec.md                                       ← (no doc de entrega; tooling interno)
    └── tasks.md                                      ← (no doc de entrega; tooling interno)
```

---

## C. Reglas innegociable (§0 user spec) — 100% respetadas

- ✅ Master intacto. Trabajo solo en `feat/fase-1-foundation`.
- ✅ Sin FastAPI/Starlette/Flask/Django.
- ✅ Sin SQLAlchemy, sin DB drivers, sin Alembic.
- ✅ Sin Redis, Kafka, RabbitMQ, Celery.
- ✅ Sin AI SDKs (OpenAI, Anthropic…).
- ✅ Sin Stripe / pasarelas.
- ✅ Sin WhatsApp/Twilio/Firebase/push.
- ✅ Sin frontend.
- ✅ Sin lógica de vertical concreto (nada de pica-pollo/hostelería).
- ✅ Sin repositories concretos.
- ✅ Sin EventBus infraestructura.
- ✅ Sin Outbox físico.
- ✅ Sin framework DI.
- ✅ Runtime `dependencies = []` (0 dependencias runtime añadidas).
- ✅ mypy strict global **no relajado**.
- ✅ Ruff no silenciado.
- ✅ AT-1..AT-9 intactos (no borrados, no debilitados).
- ✅ Domain Model 0.1 intacto (0 cambios).
- ✅ Gate 0.3 NO iniciado.
- ✅ Sin merge a master / sin tags / sin releases / sin PyPI.

---

## D. Contratos implementados (Gate 0.2)

| # | Contrato | Archivo | Tipo | Decisión / Justificación |
|---|---|---|---|---|
| 1 | `Command` | [commands.py](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/src/universal_business/application/messaging/commands.py) | frozen dataclass, kw_only=True | Marcador semántico inmutable. Frozen garantiza inmutabilidad sin escribir manualmente `__setattr__`. `kw_only=True` evita bugs de orden positional en jerarquías. |
| 2 | `Query` | [queries.py](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/src/universal_business/application/messaging/queries.py) | frozen dataclass, kw_only=True | Mismo razonamiento que Command. |
| 3 | `CommandHandler[C, R]` | [handlers.py](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/src/universal_business/application/messaging/handlers.py) | `typing.Protocol` generic, `@runtime_checkable` | Permite duck typing sin herencia rígida. Varianza: `C contravariant`, `R covariant` — correcto para handlers. Sin registry/service locator. |
| 4 | `QueryHandler[Q, R]` | [handlers.py](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/src/universal_business/application/messaging/handlers.py) | Protocol generic | Mismo razonamiento que CommandHandler. |
| 5 | `UnitOfWork` | [unit_of_work.py](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/src/universal_business/application/unit_of_work.py) | Protocol. Métodos: `__enter__`, `__exit__`, `commit`, `rollback`. | Context manager semántica frontera transaccional. **Sin `begin()` (redundante con `__enter__`). Sin commit implícito en `__exit__` (ADR-008 opción B).** `__exit__` detecta sin commit → rollback. |
| 6 | `IdempotencyKey` | [idempotency.py](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/src/universal_business/application/idempotency.py) | frozen dataclass VO + regex `^[A-Za-z0-9_-]{8,128}$` | VO validado, inmutable. Longitud 8-128 razonable para keys HTTP (`Idempotency-Key` header). |
| 7 | `IdempotencyStore` | [idempotency.py](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/src/universal_business/application/idempotency.py) | Protocol. Métodos: `get`, `reserve`, `complete`. **`tenant_id` posicional-only (`/`) obligatorio.** | 3-state FSM implícito: FREE → RESERVED → DONE. Idempotencia siempre tenant-aware (sin contextvars implícitos). |
| 8 | `DomainEventHandler[E]` | [dispatcher.py](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/src/universal_business/application/events/dispatcher.py) | Protocol generic contravariant E | Handler síncrono interno. Simple `handle(event) -> None`. |
| 9 | `DomainEventDispatcher` | [dispatcher.py](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/src/universal_business/application/events/dispatcher.py) | Clase con `_handlers: dict[type, list[handler]]`. Registro explícito `register(type, handler)`. | Orden de registro determinista. Resolución MRO: `type(event).__mro__`. `dispatch_many` eager validate materializa list primero. Excepciones propagadas (ADR-009). |
| 10 | `EventPublisher` | [publisher.py](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/src/universal_business/application/events/publisher.py) | Protocol: `publish(event)`, `publish_many(events)` default iterate. | Port para futuros adapters (Outbox/Kafka/webhooks). Ningún nombre de tecnología en el core. |
| 11 | `UseCaseHandler[In, Out]` | [execution/__init__.py](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/src/universal_business/application/execution/__init__.py) | Protocol. `handle(input) -> tuple[Out, Sequence[DomainEvent]]`. | Semántica única: handler devuelve (resultado, eventos producidos). Sin leer events del aggregate internamente; handler es responsable del output explícito. |
| 12 | `execute_use_case` | [execution/__init__.py](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/src/universal_business/application/execution/__init__.py) | Helper keyword-only args: `handler`, `input`, `unit_of_work`, `event_dispatcher`, `event_publisher`, `_collector_override`. | Encapsula flujo ADR-008 canónico: UoW → handler.handle → uow.commit → post-commit dispatch_many → publish_many. Todos kwargs-only para evitar bugs positional. |
| 13 | `VerticalExtension` | [extensions/__init__.py](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/src/universal_business/application/extensions/__init__.py) | Protocol: `name: str` property + `register(context: VerticalRegistry) -> None`. | Alineado con ADR-005: `vertical → application`. El registro pasa un contexto (registry) que la extensión puede decorar sin necesidad de imports al revés. |
| 14 | `VerticalRegistry` | [extensions/__init__.py](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/src/universal_business/application/extensions/__init__.py) | frozen=False dataclass. `extensions: list[VerticalExtension]`, `metadata: dict`. | Métodos: `register(ext)` (idempotente por name; rechaza nombre vacío; TypeError si no implementa Protocol), `sorted()`, `names()`. |
| 15 | Errores aplicación | [errors.py](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/src/universal_business/application/errors.py) | 3 clases: `ApplicationError(Exception)`, `HandlerNotFoundError(ApplicationError)`, `IdempotencyConflictError(ApplicationError)`. | Jerarquía mínima. No duplicar `DomainError`. No Result/Either monads (spec §12). |

---

## E. Architecture tests NUEVOS Gate 0.2 (AT-11/12/13/17)

| AT | Archivo | Regla | Justificación / Redundancias skip |
|---|---|---|---|
| AT-11 | [test_architecture_boundaries.py](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/tests/architecture/test_architecture_boundaries.py) | Application **NO** puede importar módulos `universal_business.api` | AT-7 ya cubría Application ⊬ Infrastructure. API es capa de entrada separada; Application no debe conocerla. |
| AT-12 | (mismo) | Application **NO** puede importar `universal_business.verticals` | Alineado con ADR-005: la dirección es `vertical → application`, nunca al revés. El core no conoce verticales concreta. |
| AT-13 | (mismo) | Application **NO** puede importar 34 frameworks/SDK prohibidos: FastAPI/Starlette/Flask/Django, SQLAlchemy/Alembic/DB drivers, Redis/Celery/Kafka/Pika/Rabbit, OpenAI/Anthropic/Gemini, Stripe/Paypal, Twilio/Firebase, React/Vue, DI frameworks. | Spec §23 obliga grep sobre application/ — AT-13 es el guardia programático + AST import/identifier detection. |
| AT-17 | (mismo) | `UnitOfWork`, `IdempotencyStore`, `EventPublisher` deben ser Protocol o ABC. **NO** pueden existir subclases concretas (no abstract, no protocol) de estos ports dentro de `application/**`. | Spec §24: Ports son abstracciones. Core NO contiene implementación concreta. |

**Skips de redundancia documentados:**
- AT-10 (App ⊬ Infrastructure) → cubierto por AT-7 (permanece).
- AT-14 (Infra skeleton-only) → cubierto por AT-8.
- AT-15 (API skeleton-only) → cubierto por AT-8.
- AT-16 (Verticals sin lógica sectorial) → cubierto por AT-8 + AT-6.

---

## F. Tests unitarios Gate 0.2 (6 suites nuevas ~95 tests)

| Archivo | Cobertura |
|---|---|
| [test_application_messaging.py](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/tests/unit/test_application_messaging.py) | Command/Query frozen immutability; `FrozenInstanceError` al mutar; Protocol `isinstance` runtime; herencia Command no rompe; HandlerNotFoundError is subclass ApplicationError; Handler protocol subclassing. |
| [test_application_uow.py](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/tests/unit/test_application_uow.py) | UnitOfWork Protocol check; FakeUnitOfWork happy path commit/rollback count; nested exception → rollback count=1 + exc propagada; **sin commit → __exit__ rollback count=1**; double-commit protegido en fake; context manager enter/exit; protocol no depende de SQLAlchemy. |
| [test_application_idempotency.py](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/tests/unit/test_application_idempotency.py) | IdempotencyStore Protocol `tenant_id` obligatorio signature check; IdempotencyKey validación regex (8ch, 128ch, rechaza símbolos); InvalidIdempotencyKeyError ValueError; FakeStore reserve/get/complete first-call; **duplicate key → reserve False**; cross-tenant isolation (mismo key en tenant_A y tenant_B no colisionan); complete actualiza result. |
| [test_application_events.py](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/tests/unit/test_application_events.py) | FakeEventPublisher count events list; dispatcher register single handler; **MRO dispatch**: handler DomainEvent genérico recibe evento subtipo; **orden determinista** (orden registro); no-op handler; error handler propagate (aborta + restantes no ejecutan); `dispatch(non-DomainEvent)` → ApplicationError; `dispatch_many([n,..,non-event,..])` **eager validate** → error ANTES de llamar handler #0; dispatch_many list with events; DomainEventHandler isinstance runtime. |
| [test_application_usecase.py](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/tests/unit/test_application_usecase.py) | UseCaseHandler isinstance runtime; happy path: commit=1, dispatcher recibió events, publisher recibió events, resultado correcto; **handler exc → rollback=1, commit=0, dispatcher 0, publisher 0**; **commit exc → rollback=1, 0 eventos**; _collector_override sustituye eventos; tenant_id explícito no usa contextvars; execute_use_case kwargs-only → error si positional. |
| [test_application_verticals.py](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/tests/unit/test_application_verticals.py) | VerticalExtension isinstance runtime; registry register; **doble register mismo name → idempotent no-op**; invalid empty name → ValueError; `names()` devuelve orden register; `sorted()` devuelve ordenado por nombre; rejected si no tiene name property (TypeError); rejister no llama register si es duplicado. |

---

## G. Criterios de aceptación Gate 0.2 (34 items §24 user spec) — Todos ✅

| # | Criterio | Verificación |
|---|---|---|
| 1 | Application Layer existe y es utilizable | Estructura application/ 14 módulos + 95 tests new |
| 2 | Commands / Queries definidos | Command frozen / Query frozen |
| 3 | Handlers tipados | Protocol genéricos varianza |
| 4 | UnitOfWork contract definido | UnitOfWork Protocol |
| 5 | rollback/commit semantics testeadas | FakeUnitOfWork 8 tests |
| 6 | Idempotency contract definido | IdempotencyKey + IdempotencyStore |
| 7 | tenant isolation explícito | tenant_id posicional-only signature check tests |
| 8 | DomainEvent dispatching lógico operativo | DomainEventDispatcher ~14 tests |
| 9 | EventPublisher port definido | EventPublisher Protocol |
| 10 | events no publicados antes de commit | execute_use_case tests: exc/commit-fail → publisher 0 |
| 11 | application no importa infrastructure | AT-7 (pre-existente) pasa |
| 12 | application no importa API | AT-11 pasa |
| 13 | no frameworks externos | AT-13 pasa + §23 grep empty |
| 14 | no runtime dependencies nuevas | pyproject.toml dependencies = [] |
| 15 | architecture tests nuevos pasan | AT-11/12/13/17 passing |
| 16 | tests previos siguen pasando | 418 baseline tests passing (pytest -q) |
| 17 | Ruff pasa | ruff check . |
| 18 | Ruff format pasa | ruff format --check . |
| 19 | mypy strict pasa | mypy src |
| 20 | Python 3.11 compatible | CI matrix + test suite |
| 21 | Python 3.12 compatible | CI matrix |
| 22 | docs actualizados | DEVELOPMENT_STATUS, plan 0.2, ADR-008/009, ARCHITECTURE.md |
| 23 | scope 0.3+ no iniciado | No CreateOrder/etc., no infra/api/verticals code, no DB, no FastAPI |
| 24 | Command/Query immutable | frozen dataclass tests |
| 25 | UnitOfWork context manager | __enter__/__exit__ Protocol |
| 26 | No commit implícito | test_no_commit_causes_rollback_exit |
| 27 | Idempotency 3 state | reserve/get/complete flow |
| 28 | Dispatcher deterministic order | handler_sequence test |
| 29 | Dispatcher MRO | test_event_mro_dispatch |
| 30 | dispatch_many eager | test_dispatch_many_eager_rejects_non_domain_event |
| 31 | UseCase tuple[result, events] signature | UseCaseHandler Protocol + tests |
| 32 | VerticalRegistry idempotent | test_vertical_registry_idempotent_duplicate |
| 33 | Ports Protocol are abstractions | AT-17 validate |
| 34 | application no importa verticals | AT-12 pasa |

---

## H. Explicitly deferred (fuera de scope 0.2) — NO implementado

1. **Persistencia real (repositories concretos, SQLAlchemy, DB, Alembic)** → Gate 0.5.
2. **API layer (FastAPI, Starlette, endpoints, Pydantic)** → Gate 0.5.
3. **Casos de uso concretos (CreateOrder, PlaceOrder, CreateReservation, ...)** → Gate 0.3/0.4.
4. **Outbox físico / EventBus infraestructura / Kafka / RabbitMQ** → Gate 0.5/0.6.
5. **Global tenant context / contextvars / middleware tenant resolver** → Gate 0.5 (cuando haya API).
6. **Cualquier implementación concreta de UnitOfWork / IdempotencyStore / EventPublisher** → Gate 0.5 (infrastructure/).
7. **Vertical concreto (pica-pollo u otro)** → Gate 0.6.
8. **Pricing avanzado / SKU / variantes / stock real** → Gate 0.3.
9. **Motor de disponibilidad / scheduling** → Gate 0.3/0.4.
10. **Result/Either monads** → No requeridos en 0.2 (jerarquía Exception simple suficiente).
11. **Service locator / DI container / registry global de handlers** → rechazados por diseño; registro explícito siempre.

---

## I. Validación obligatoria — comandos exactos (§22 user spec)

```bash
# 1. Tests
python -m pytest -q

# 2. Lint
ruff check .

# 3. Format check
ruff format --check .

# 4. Typing
mypy src

# 5. Git whitespace
git diff --check

# 6. Scope audit (no cambiar infra/api/verticals salvo __init__)
git status
git diff master...HEAD --name-only

# 7. Grep innombrables en application (§23)
grep -RniE "fastapi|starlette|sqlalchemy|redis|celery|kafka|pika|openai|anthropic|stripe|twilio|firebase" src/universal_business/application/ || true
```

---

## J. Siguiente Gate

**Gate 0.3 — Catalog & Resources.** Scope tentativo (requiere plan formal nuevo antes de empezar):
- Casos de uso reales de Catalog & Resources (CreateItem, UpdatePrice, etc.).
- Pricing / SKU / variantes / capacity / stock lógico.
- Primeros repositories concretos **o aún no** (se decidirá en el plan 0.3).
- Continúa sin FastAPI / SQLAlchemy si es viable o se introduce el primer adapter real de infraestructura (si el plan 0.3 lo aprueba).

**Prohibido empezar Gate 0.3 sin:**
- Merge de Gate 0.2 al baseline.
- Spec + tasks formales aprobados.
- Nueva rama (ej: `feat/fase-2-catalog-resources`).
