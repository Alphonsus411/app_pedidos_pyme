# Especificación — Gate 0.2 Foundation / Application Layer

**Proyecto:** Universal Business Core (`universal_business`)
**Rama objetivo:** `feat/fase-1-foundation`
**Baseline de referencia:** `master @ 4947f06` (merge commit Gate 0.1)
**HEAD inicial de la fase:** `4947f06` (árbol limpio, master = HEAD)
**Ciclo de vida spec:** Draft → Approved → Implemented → Reviewed

---

## 1. Problema, usuarios y objetivos

### 1.1 Problema
Gate 0.1 (Architectural Baseline) define el modelo de dominio, los VOs compartidos, los
Repository Ports, los tests arquitectónicos AT-1..AT-9 y la estructura de capas 4-niveles
(Domain ← Infrastructure; Domain → Application → API). Pero:

- la capa `application/` está vacía (solo `__init__.py` con docstring),
- no existe patrón explícito para *ejecutar casos de uso*,
- no hay contrato de frontera transaccional (UnitOfWork),
- no hay contrato de idempotencia para deduplicación futura,
- `DomainEvent` existe pero no hay coordinación lógica (dispatcher interno / publisher externo),
- no hay contratos tipados para Command/Query/Handler,
- la puerta para extensiones verticales (ADR-005) solo existe en el texto de ADR, no
  como contrato explícito en Python.

Sin estos contratos mínimos, la siguiente fase (0.3 Catalog/Resources, 0.4 Orders/Reservations)
no puede implementar casos de uso reales sin riesgo de acoplar el core a tecnologías concretas
o de crear "servicios anémicos" sin límites definidos.

### 1.2 Usuarios (consumidores directos)
- **Ingenieros Fases 0.3..0.7:** escribirán Use Cases reales apoyándose en los contratos de 0.2.
- **Ingenieros verticales (ADR-005):** usarán `VerticalExtension` para extender comportamiento
  sin contaminar `domain/` ni `application/`.
- **Ingenieros Infrastructure (próximamente):** implementarán los ports Protocol sin tocar
  la aplicación.
- **QA / Revisiones:** usarán los tests arquitectónicos AT-10..AT-17 como puertas de calidad.

### 1.3 Objetivos de Gate 0.2
1. **Contratos ejecutables:** Command/Query/Handler genéricos tipados, UnitOfWork port,
   Idempotency port, DomainEventDispatcher lógico, EventPublisher externo port, Use Case
   execution pattern y VerticalExtension contract.
2. **Reglas semánticas fijadas y documentadas:**
   - Transaction boundary (commit OK → luego dispatch y publish; error → rollback y NADA de eventos).
   - Idempotency `tenant_id` explícito cuando aplica.
   - Domain events: originados en dominio por `AggregateRootMixin`, recolectados por la
     capa de aplicación, **nunca** publicados antes de `commit`.
3. **Tests AT nuevos** (AT-10..AT-17) complementando AT-1..AT-9 existentes *sin debilitar*.
4. **Tests unitarios** (FakeUnitOfWork, FakeEventPublisher, FakeIdempotencyStore, FakeHandler)
   que demuestran comportamiento esperado.
5. **Cero runtime dependencies.** `dependencies = []` intacto en `pyproject.toml`.
6. **Compatibilidad Python 3.11 / 3.12.** CI matrix sin cambios.
7. **Mypy strict global PASS, Ruff lint PASS, Ruff format check PASS.**
8. **Documentación actualizada:** `DEVELOPMENT_STATUS.md`, opcionalmente
   `docs/plan_entrega_0.2_foundation.md`, y 0 o 2 ADRs nuevos
   (transaction semantics, event dispatch semantics) si la decisión no es trivial.

---

## 2. No-objetivos (explícitamente fuera de scope)

Lo siguiente **NO** se implementa en Gate 0.2:

| Ítem | Motivo |
|---|---|
| FastAPI, Starlette, Flask, Django | Gate 0.5 (API) |
| SQLAlchemy, Alembic, drivers DB, PostgreSQL/SQLite/MySQL | Gate 0.5 (Persistence) |
| Redis, Kafka, RabbitMQ, Celery, Pika | Fase ≥0.6 |
| WhatsApp, Twilio, Firebase, SMS, push | Fase ≥0.7 |
| OpenAI / Anthropic SDK | Jamás sin plan aprobado. |
| Stripe / pasarelas de pago | Fase Payments >0.4. |
| Vertical concreto (pica-pollo, hostelería, clínica, etc.) | ADR-005. |
| Repositories concretos, EventBus real, Outbox físico | Infra (Gate 0.5 / 0.6). |
| Frameworks DI, service locators, registry global, autodiscovery mágico | Prohibido por 0.1 quality rules. |
| Casos de uso funcionales (CreateOrder, CreateReservation, PlaceOrder…) | Fases 0.3 / 0.4. |
| Result/Either monads, CQRS buses sofisticados | Decisiones futuras. |
| Gate 0.3, 0.4, 0.5 iniciado. | Tarea 27 del usuario: NO. |
| Release / tags / PyPI publish. | Fuera de scope. |
| Merge a master automático. | Prohibido hasta revisión humana. |

---

## 3. Requisitos funcionales (RF)

### RF-1 Application layer existe y es utilizable
`src/universal_business/application/` debe contener módulos Python (no solo `__init__.py`)
con importaciones limpias que **solo** dependen de `universal_business.domain.*` y stdlib.

### RF-2 Messaging primitives
- **Command / Query** como marcadores semánticos base, framework-agnostic.
- Immutabilidad preferida (`@dataclass(frozen=True, kw_only=True)`) cuando aplique.
- Ambos pueden llevar `tenant_id` explícito cuando operan sobre datos tenant-owned. No
  se permite `tenant_id` implícito por contexto global / `contextvars` / middleware.

### RF-3 Handler contracts
- `CommandHandler[CommandT: Command, ResultT]` como Protocol genérico o ABC con firma
  `handle(command: CommandT) -> ResultT`.
- `QueryHandler[QueryT: Query, ResultT]` similar.
- Generics correctos, mypy strict PASS sin `# type: ignore` injustificado.
- No registro global. No bus. No reflection. Handlers instanciables con dobles manuales.

### RF-4 UnitOfWork port (Protocol)
Firma mínima:
- `__enter__() -> Self`
- `__exit__(exc_type, exc, tb) -> None`  (rollback si `exc is not None`, commit implícito
  o explícito según semántica elegida; documentar cuál).
- `commit() -> None`
- `rollback() -> None`

Debe poder extenderse por módulos de infraestructura sin cambios aquí. **No debe asumir
SQLAlchemy ni flush/commit DB.**

### RF-5 Transaction boundary semantics (regla dura)
Para cualquier ejecución orquestada:
1. Entra en `UnitOfWork` (context manager o `begin` explícito).
2. Ejecuta lógica de dominio/orquestación.
3. `commit()` solo si todo OK.
4. Solo **después de commit exitoso** se permite:
   a. `DomainEventDispatcher.dispatch_many(events_collected)` (handlers síncronos internos).
   b. `EventPublisher.publish_many(events_collected)` (port externo).
5. Si la lógica levanta excepción **o** `commit()` falla → `rollback()` y NO se publica NADA.

Prohibido doble commit; prohibido publicar eventos antes de commit. Probar con FakeUnitOfWork.

### RF-6 Idempotency contracts
- `IdempotencyKey`: value object mínimo o simple `str` wrapper documentado.
- `IdempotencyStore` Protocol con operaciones mínimas (sugeridas 3 operaciones):
  - `get(tenant_id, key) -> Resultado grabado | None`  (lectura).
  - `reserve(tenant_id, key, request_digest) -> bool` (marca que el procesamiento empieza;
    retorna `False` si ya está reservado/procesado).
  - `complete(tenant_id, key, result_digest) -> None` (marca procesamiento completado).
- `tenant_id` **siempre** explícito en las 3 operaciones (idempotencia por tenant).

### RF-7 DomainEvent Dispatching lógico
- `DomainEventHandler[EventT: DomainEvent]` Protocol genérico: `handle(event: EventT) -> None`.
- `DomainEventDispatcher`:
  - Registro explícito `register(event_type: type[DomainEvent], handler)`.
  - Resuelve handlers por tipo de evento, orden determinista (orden de registro).
  - Múltiples handlers por evento permitidos.
  - Ningún handler registrado → comportamiento documentado (no-op, no error).
  - Excepción de un handler debe propagarse o envolverse en `ApplicationError` específico;
    documentar comportamiento.
- NO asíncrono. NO Kafka/Redis/Celery. Solo coordinación síncrona, framework-agnostic.

### RF-8 EventPublisher external port
- `EventPublisher` Protocol, separado de `DomainEventDispatcher` (distinción A/B explícita).
- Operaciones `publish(event: DomainEvent) -> None` y/o `publish_many(events: Iterable[DomainEvent]) -> None`.
- Futuros backends (Outbox físico, Kafka, RabbitMQ, webhooks) implementarán este protocol.
- Nada en el nombre de la clase/Protocol menciona tecnología concreta.

### RF-9 Use Case execution pattern
- Patrón mínimo para orquestar (entrada → UoW → lógica dominio → recolecta eventos →
  commit → dispatch → publish → resultado).
- Evitar jerarquías profundas de clases base. Puede ser `UseCase` dataclass composable o
  simplemente una `UseCaseHandler[InT, OutT]` Protocol + una función helper `execute_use_case(...)`.
- Debe servir a los casos de prueba unitarios felices/tristes sin frameworks.

### RF-10 Vertical extension contract (ADR-005)
- `VerticalExtension` Protocol con `name: str` y al menos un hook mínimo (p. ej.
  `register(self, context: VerticalRegistry) -> None`).
- La capa de aplicación NO importa ningún módulo bajo `verticals/*`.
- Los nombres sectoriales siguen prohibidos dentro de `application/*` (AT-6 continúa aplicando).

### RF-11 Errores capa aplicación
Minimizar jerarquía; si son necesarios:
- `ApplicationError(Exception)` base.
- `HandlerNotFoundError` (si algún dispatcher no encuentra handlers y el comportamiento
  elegido es error).
- `IdempotencyConflictError` cuando `reserve` falla por key ya procesada.

No duplicar `DomainError` existente en `domain/shared/errors.py`.

---

## 4. Requisitos no funcionales (RNF)

### RNF-1 Framework agnostic
100% stdlib + `universal_business.domain.*`. Ningún import externo runtime.

### RNF-2 Mypy strict global
`mypy src` Success sin exceptions. No se añaden `[[tool.mypy.overrides]]` laxos.

### RNF-3 Calidad estática
`ruff check .` 0 errores. `ruff format --check .` 0 cambios.

### RNF-4 Zero runtime deps
`pyproject.toml` → `dependencies = []`. Si se requiere una dependencia: justificar,
obtener aprobación explícita, y solo entonces añadirla. Objetivo: mantener `[]`.

### RNF-5 Python 3.11 / 3.12 compat
CI matrix se mantiene `["3.11","3.12"]`. Ninguna sintaxis 3.13+.

### RNF-6 Arquitectura intacta
Ningún cambio a `domain/*` salvo "cambio mínimo justificado, documentado, con tests".
Tests AT-1..AT-9 existentes PASS sin desactivar.

### RNF-7 Coverage direction
Conteo tests total ≥ tests de la baseline. Baseline Gate 0.1 sobre master 4947f06: se espera
un aumento del ~15-30% con nuevos tests doc, handlers, UoW, idempotency, events, execution.

### RNF-8 Aderencia al principio rector
Preferir: contratos pequeños, composición, explicitud, tipado fuerte, dependencias
invertidas, cero magia. Por encima de: frameworks, abstracciones prematuras, buses
complejos, registries globales, service locators, infraestructura anticipada.

---

## 5. Restricciones / dependencias / asunciones

### 5.1 Restricciones (hard rules)
- Rama: `feat/fase-1-foundation` exclusivamente.
- Base de trabajo: `master @ 4947f06`.
- Prohibido tocar `infrastructure/` salvo comentarios o `__init__` estrictamente necesarios.
- Prohibido tocar `api/` salvo comentarios o `__init__` estrictamente necesarios.
- Prohibido crear releases/tags/merge.
- 14 items del punto 0 (innombrables) prohibidos de forma absoluta.

### 5.2 Dependencias
- **Gate 0.1 cerrado y mergeado:** confirmado (master 4947f06).
- **Eventos de dominio 0.1:** `DomainEvent` frozen + `AggregateRootMixin.domain_events` list.
- **Tests arquitectónicos AST framework:** iter_python_files / collect_imports helpers disponibles.
- **fpdf2 optional extra [docs]:** puede usarse si se genera PDF, pero no se añade runtime.

### 5.3 Asunciones razonables
1. La orquestación en 0.2 es síncrona. Async se pospone (Gate ≥0.4+).
2. `DomainEventDispatcher` de aplicación no tiene que ser thread-safe; responsabilidad de los
   adapters de infra si lo necesitan.
3. Idempotency de 0.2 solo define *interfaces*. Fake implementación en tests es suficiente.
4. El UnitOfWork en 0.2 NO implementa `flush()`, `savepoints`, ni `nested()`; el protocol
   puede extenderse después sin romper BC si usamos Protocol, no ABC rígido.

---

## 6. Criterios de Aceptación (AC) — tipo `rule` o `rubric`

### Reglas (rule) — binarias verificables
- **AC-R-01:** Module path `src/universal_business/application/messaging/commands.py` define
  un marcador Command (ABC o Protocol o frozen dataclass base).
- **AC-R-02:** Module path `src/universal_business/application/messaging/queries.py` define
  un marcador Query.
- **AC-R-03:** Module path `src/universal_business/application/messaging/handlers.py` define
  `CommandHandler[CommandT, ResultT]` y `QueryHandler[QueryT, ResultT]` con generics correctos.
- **AC-R-04:** Module `unit_of_work.py` contiene un Protocol (o ABC) `UnitOfWork` con métodos
  `__enter__`, `__exit__`, `commit`, `rollback`.
- **AC-R-05:** Module `idempotency.py` contiene `IdempotencyStore` Protocol con
  `tenant_id` explícito en firma de `get / reserve / complete`.
- **AC-R-06:** Module `events/dispatcher.py` define `DomainEventHandler[EventT]` y
  `DomainEventDispatcher` con registro explícito.
- **AC-R-07:** Module `events/publisher.py` define `EventPublisher` Protocol con
  `publish` o `publish_many`.
- **AC-R-08:** Module `execution/use_case.py` define un patrón ejecutable (UseCase o
  UseCaseHandler o execute_use_case).
- **AC-R-09:** Module `extensions/verticals.py` define `VerticalExtension` Protocol.
- **AC-R-10:** 0 imports de los 14 innombrables en `src/universal_business/application/**`.
  (Grep de AST debe devolver 0 matches; AT-13 en tests).
- **AC-R-11:** `pyproject.toml [project] dependencies = []` (exactamente igual que baseline).
- **AC-R-12:** AT-1..AT-9 existentes PASS sin modificar ni desactivar.
- **AC-R-13:** Tests nuevos AT-10 Application ⊬ Infrastructure  **PASS**.
- **AC-R-14:** AT-11 Application ⊬ API  **PASS**.
- **AC-R-15:** AT-12 Application ⊬ verticals concretos  **PASS**.
- **AC-R-16:** AT-13 Application ⊬ frameworks/SDK externos  **PASS**.
- **AC-R-17:** AT-14 Infrastructure skeleton-only (<15 LOC)  **PASS**.
- **AC-R-18:** AT-15 API skeleton-only (<15 LOC)  **PASS**.
- **AC-R-19:** AT-16 Verticals sin lógica sectorial concreta  **PASS**.
- **AC-R-20:** AT-17 UoW / EventPublisher / Idempotency son abstracciones Protocol/ABC,
  sin implementación concreta (en `application/`)  **PASS**.
- **AC-R-21:** `python -m pytest` — 0 fallos.
- **AC-R-22:** `ruff check .` — All checks passed.
- **AC-R-23:** `ruff format --check .` — 0 files changed.
- **AC-R-24:** `mypy src` — Success.
- **AC-R-25:** `git diff --check` — 0 whitespace errors.
- **AC-R-26:** Tests: FakeUnitOfWork rollback en excepción, commit solo en éxito.
- **AC-R-27:** Tests: FakeEventPublisher `publish_many` se llama solo si `commit` tuvo éxito.
- **AC-R-28:** Tests: FakeIdempotencyStore `reserve` devuelve `False` cuando la misma
  `(tenant_id, key)` ya fue completada.
- **AC-R-29:** Tests: DomainEventDispatcher llamado N handlers determinista en orden registro.
- **AC-R-30:** `DEVELOPMENT_STATUS.md` actualizado con Gate 0.2 status y scope real.
- **AC-R-31:** Rama `feat/fase-1-foundation` HEAD corresponde a 1 único commit de cierre
  `feat(application): establish Gate 0.2 foundation layer` (o a commits serializados; no
  merge sin aprobación). Working tree clean después de commit.

### Rúbricas (rubric) — evaluativas, con umbral de aprobación
- **AC-E-01: Arquitectura y separación de concerns** (escala 0-3, umbral ≥2)
  - 3: Capas perfectamente segregadas; ningún acoplamiento sorpresa; Ports & Adapters visible.
  - 2: Pequeño defecto sin impacto (ej: un module con helper que podría ir en otro sitio).
  - 1: Un acoplamiento real (application depende de algo no permitido; corregible con edits).
  - 0: Múltiples violaciones de límites (debe ir a remediación).
- **AC-E-02: Testabilidad** (escala 0-3, umbral ≥2)
  - 3: Todos los contratos tienen fakes; escenarios felices + fallo + edge cases.
  - 2: Happy path + un caso triste; algún contrato solo se prueba indirectamente.
  - 1: Solo happy paths; varios contratos sin tests unit directos.
  - 0: Tests arquitectónicos o unitarios faltantes o que no demuestran comportamiento.
- **AC-E-03: Doc y legibilidad** (escala 0-3, umbral ≥2)
  - 3: DEVELOPMENT_STATUS completo, módulos application con docstrings claros, sin magia.
  - 2: Docs presentes pero concisos; docstrings en contratos pero escasos.
  - 1: Falta DEVELOPMENT_STATUS actualizado; pocos docstrings.
  - 0: Documentación vacía o contradictoria.

---

## 7. Preguntas abiertas al finalizar Spec (resueltas en Plan/Implement si quedaban)

1. **UnitOfWork: begin() separado o context-manager solo?** → Resuelto en implementación:
   `__enter__` + `__exit__` (implica begin al entrar). `commit()` explícito si el usuario
   quiere; `__exit__` no hace commit implícito (solo rollback en caso de excepción).
   *Razón:* semántica más segura contra commits accidentales.
2. **DomainEventDispatcher: error o no-op cuando no hay handlers?** → Resuelto: no-op
   (solo se registra un logging-level event interno; pero logging es stdlib y es opcional).
3. **EventPublisher: publish() simple o publish_many() asincrónico?** → Resuelto: ambos
   disponibles, ambos síncronos; el protocol sugiere `publish` + `publish_many` (con
   implementación default trivial de `publish` como `publish_many([event])` o viceversa).
4. **ADR nuevos? 0, 1 o 2?** → Plan: 2 ADRs si ambas decisiones (transaction semantics,
   event dispatch semantics) no son triviales y vale la pena fijarlas como decisiones
   arquitectónicas permanentes; 0 si ya quedan suficientemente explicados en docstrings
   y tests.

