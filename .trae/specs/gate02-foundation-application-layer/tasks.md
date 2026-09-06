# Plan de Implementación — Gate 0.2 Foundation / Application Layer

**Spec asociado:** [spec.md](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/.trae/specs/gate02-foundation-application-layer/spec.md)
**Rama:** `feat/fase-1-foundation`
**Baseline:** `master @ 4947f06`

Orden de ejecución estricto: T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8.

---

## Task 1: Messaging contracts + Application errors (Wave 1)

**Dependencies:** ninguna.  **Priority:** high.

### Scope
- Crear `src/universal_business/application/messaging/__init__.py`.
- Crear `src/universal_business/application/messaging/commands.py`  (Command base frozen dataclass).
- Crear `src/universal_business/application/messaging/queries.py`   (Query base frozen dataclass).
- Crear `src/universal_business/application/messaging/handlers.py`  (Protocol CommandHandler[CommandT, ResultT] / QueryHandler[QueryT, ResultT]).
- Añadir a `application/__init__.py` exports mínimos (si mejora discoverability, no obligatorio).
- Si son necesarios: `ApplicationError`, `HandlerNotFoundError`, `IdempotencyConflictError` en `application/errors.py` (NO duplicar `DomainError`).

### Test Requirements locales (TR)
- **TR-T1-R1 [rule]:** `Command` instanciable frozen; 2 commands concretos (de prueba) no se mutan.
- **TR-T1-R2 [rule]:** `Query` instanciable frozen.
- **TR-T1-R3 [rule]:** Un `FakeHandler(CommandHandler[Command, Result])` se instancia, se pasa un
  command a `handler.handle()` y devuelve Result esperado.
- **TR-T1-R4 [rule]:** mypy strict sin ignores en estos 4 módulos.
- **TR-T1-E1 [rubric 0-2, ≥1 OK]:** legibilidad docstrings (0 = sin docstrings, 2 = cada
  Protocol/ABC lleva docstring explicando propósito y semántica).

### Completion Evidence
Tests unitarios en `tests/unit/test_application_messaging.py` PASS.

---

## Task 2: UnitOfWork Protocol + Idempotency Protocol (Wave 2)

**Dependencies:** T1.  **Priority:** high.

### Scope
- Crear `src/universal_business/application/unit_of_work.py`  → `UnitOfWork(Protocol)`.
- Crear `src/universal_business/application/idempotency.py`  → `IdempotencyKey` value-object /
  wrapper str mínimo, y `IdempotencyStore(Protocol)` con `get / reserve / complete` **con
  `tenant_id` explícito keyword-only o posicional** (nunca implícito).
- Errores `IdempotencyConflictError` (si no estaba en T1).

### Test Requirements locales (TR)
- **TR-T2-R1 [rule]:** `FakeUnitOfWork` como context manager: si el bloque NO lanza excepción,
  `commit_count == 1`, `rollback_count == 0`.
- **TR-T2-R2 [rule]:** `FakeUnitOfWork` como context manager: si el bloque lanza `ValueError`,
  `commit_count == 0`, `rollback_count == 1` (excepción se propaga fuera del `with`).
- **TR-T2-R3 [rule]:** `FakeUnitOfWork`: llamada manual a `commit()` después de un `rollback()`
  no cambia el estado del fake.
- **TR-T2-R4 [rule]:** UnitOfWork Protocol: `inspect.signature(uow.__enter__)`, `.__exit__`,
  `.commit`, `.rollback` son los 4 miembros exigidos.
- **TR-T2-R5 [rule]:** FakeIdempotencyStore: 1.ª llamada `reserve(tid,k,d)` → `True`; 2.ª
  misma `(tid,k,d)` ya reservada → `False` (conflicto).
- **TR-T2-R6 [rule]:** FakeIdempotencyStore: cross-tenant no confunde keys.
  `reserve(tid_A,k,d) == True`; `reserve(tid_B,k,d) == True` (tenant distinto).
- **TR-T2-R7 [rule]:** IdempotencyStore Protocol: 3 métodos públicos **llevan** `tenant_id`
  en firma (verificado via `inspect.signature`).
- **TR-T2-E1 [rubric 0-2, ≥1 OK]:** docstrings de UnitOfWork explican semántica: cuándo se
  hace commit / rollback, y la prohibición de publicar eventos antes de commit.

### Completion Evidence
Tests unitarios en `tests/unit/test_application_uow.py` y `tests/unit/test_application_idempotency.py` PASS.

---

## Task 3: DomainEvent Dispatcher + EventPublisher ports (Wave 3)

**Dependencies:** T1, T2.  **Priority:** high.

### Scope
- Crear `src/universal_business/application/events/__init__.py`.
- Crear `src/universal_business/application/events/dispatcher.py`  →
  `DomainEventHandler[EventT: DomainEvent]` Protocol +
  `DomainEventDispatcher` class con registro explícito
  `register(event_type, handler)` / `dispatch(event)` / `dispatch_many(events)`.
  Orden de handlers determinista (orden de registro). Sin autodiscovery.
- Crear `src/universal_business/application/events/publisher.py`  →
  `EventPublisher(Protocol)` con `publish` y `publish_many` (ambos métodos disponibles;
  `publish` puede ser helper trivial sobre `publish_many` o viceversa).

### Test Requirements locales (TR)
- **TR-T3-R1 [rule]:** 1 evento → 1 handler se llama exactamente una vez.
- **TR-T3-R2 [rule]:** 1 evento → 2 handlers registrados (orden A, B) se invocan en orden
  A, B (determinista).
- **TR-T3-R3 [rule]:** Evento sin handlers registrado → dispatch no-op (no error).
- **TR-T3-R4 [rule]:** Handler A lanza error → se propaga (o se envuelve en `HandlerNotFoundError`
  / `ApplicationError`; **decisión: propagar la excepción original con contexto, sin
  silenciar.**). Comportamiento documentado.
- **TR-T3-R5 [rule]:** FakeEventPublisher `publish_many(events)` guarda los eventos recibidos.
- **TR-T3-R6 [rule]:** Distinción conceptual A/B visible: `dispatcher` ≠ `publisher` (distinto
  módulo, distinto tipo).
- **TR-T3-R7 [rule]:** `DomainEventDispatcher.dispatch_many` no recibe `Sequence[int]` u objetos
  no-DomainEvent sin error; usar isinstance check y lanzar `ApplicationError` si un elemento
  no es DomainEvent (explicitemente exigido).

### Completion Evidence
Tests en `tests/unit/test_application_events.py` PASS.

---

## Task 4: UseCase execution pattern + VerticalExtension contract (Wave 4)

**Dependencies:** T1..T3.  **Priority:** high.

### Scope
- Crear `src/universal_business/application/execution/__init__.py`.
- Crear `src/universal_business/application/execution/use_case.py`  →
  `UseCaseHandler[InT, OutT]` Protocol, y una función helper o clase composable
  `execute_use_case(...)` **que garantice la semántica 0.2**:
  1. entrar UoW,
  2. ejecutar handler lógica (orquestación),
  3. recolectar domain events desde los aggregates (la función NO lo hace por arte de magia;
     el orquestador los devuelve o se los pasamos),
  4. commit(),
  5. dispatch_many(events),
  6. publish_many(events),
  7. devolver resultado;
  si cualquier paso 1..3 levanta excepción → rollback, NADA de dispatch/publish.
- Crear `src/universal_business/application/extensions/__init__.py`.
- Crear `src/universal_business/application/extensions/verticals.py`  →
  `VerticalExtension` Protocol con `name: str` y un hook `register(...)` mínimo.
  La capa aplicación **no importa** módulos en `verticals/`.

### Test Requirements locales (TR)
- **TR-T4-R1 [rule]:** Happy path use case: orquestador ficticio que añade un DomainEvent,
  devuelve "ok". Resultado: commit_count == 1, dispatch recibío evento, publisher recibió
  evento.
- **TR-T4-R2 [rule]:** Failure path use case: orquestador lanza `ValueError` antes de return.
  Resultado: rollback_count == 1, commit_count == 0, **publisher publicó 0 eventos**,
  **dispatcher llamó a 0 handlers**.
- **TR-T4-R3 [rule]:** VerticalExtension Protocol: 2 fakes que implementan `name` + `register`
  se instancian y registran correctamente (sin imports de vertical/*).
- **TR-T4-R4 [rule]:** Tenancy: orquestador ficticio recibe `tenant_id` explícito; al finalizar,
  todos los DomainEvent producidos llevan `tenant_id == input`.

### Completion Evidence
Tests en `tests/unit/test_application_usecase.py` y `tests/unit/test_application_verticals.py` PASS.

---

## Task 5: Architecture tests AT-10..AT-17 (Wave 5)

**Dependencies:** T1..T4.  **Priority:** high.

### Scope
- Editar `tests/architecture/test_architecture_boundaries.py`:
  - Extender `FORBIDDEN_IMPORTS_FROM_APPLICATION = FORBIDDEN_IMPORTS_FROM_DOMAIN | {infrastructure, api modules, verticals modules}`.
  - Añadir tests `test_AT_10_application_no_import_infrastructure`,
    `test_AT_11_application_no_import_api`,
    `test_AT_12_application_no_import_verticals`,
    `test_AT_13_application_no_frameworks_or_external_sdks`,
    `test_AT_14_infrastructure_skeleton_only` (<15 LOC non-whitespace por módulo),
    `test_AT_15_api_skeleton_only`,
    `test_AT_16_verticals_no_sectorial_logic` (0 módulos python > 15 LOC excepto __init__),
    `test_AT_17_uow_idempotency_eventpublisher_are_ports_only` (los símbolos `UnitOfWork`,
    `IdempotencyStore`, `EventPublisher` en `application/*` son `Protocol` o `ABC`, no
    `class` concrete con implementación).
- Asegurar que AT-1..AT-9 siguen PASS sin tocar.

### Test Requirements locales (TR)
- **TR-T5-R1 [rule]:** AT-10 a AT-17 existen y devuelven PASS.
- **TR-T5-R2 [rule]:** Ejecutar tests completos `pytest` → 0 fallos, conteo tests ≥ baseline + 25.
- **TR-T5-R3 [rule]:** Tests AT nuevos cubren application/ + infrastructure/ + api/ + verticals/
  (compruebo que las 4 carpetas aparecen en asserts).

### Completion Evidence
`pytest -q tests/architecture/` PASS.

---

## Task 6: Documentación DEVELOPMENT_STATUS.md + plan_entrega_0.2.md + ADRs (Wave 6)

**Dependencies:** T5.  **Priority:** medium.

### Scope
- Actualizar `docs/DEVELOPMENT_STATUS.md`:
  Gate 0.2 status, branch, baseline master=4947f06, Scope implemented, Explicitly deferred,
  Validation commands, Known limitations, Next Gate.
- Opcional: crear `docs/plan_entrega_0.2_foundation.md` siguiendo la misma estructura
  de `docs/plan_entrega_0.1_architectural_baseline.md` pero para Gate 0.2 (NO PDF salvo
  orden explícito posterior).
- Opcional: 2 ADRs nuevos en `docs/adr/`
  - `ADR-008-application-transaction-semantics.md`  (explica paso 1..7 + rollback/error).
  - `ADR-009-domain-event-dispatch-publish-semantics.md` (explica A/B: internal dispatcher vs
    external publisher; por qué eventos solo después de commit).
- Opcional: actualizar `docs/ARCHITECTURE.md` sección Application Layer (antes solo decía
  "Use Cases" vacía).

### Test Requirements locales (TR)
- **TR-T6-R1 [rule]:** DEVELOPMENT_STATUS.md nuevo mención Gate 0.2 y dice "NOT STARTED" para
  Gate 0.3+; contiene comando `pytest` y `mypy src` en validation commands.
- **TR-T6-R2 [rule]:** Los ADRs nuevos (si se crean) tienen estado "Aceptado" y consecuencias
  positivas/negativas.
- **TR-T6-E1 [rubric 0-2, ≥1 OK]:** DEVELOPMENT_STATUS.md útil para retomar en 6 meses
  (contiene rama, baseline, scope, deferred, next steps).

### Completion Evidence
Archivos docs presentes y ruff format check PASS después de updates.

---

## Task 7: Quality gate + regenerar PDF si aplica + git diff --check (Wave 7)

**Dependencies:** T1..T6.  **Priority:** high.

### Scope
- Ejecutar en orden exacto:
  1. `python -m pytest -q`
  2. `ruff check .`
  3. `ruff format --check .`
  4. `mypy src`
  5. `git diff --check`
  6. `git status`  (working tree limpio después de commits parciales? No; al final de T7 debe
     haber cambios que T8 comitee).
- Auditar scope: `git diff master...HEAD --name-only`  → cambios SOLO en:
  `src/universal_business/application/**`, `tests/{architecture,unit}/test_*.py`,
  `docs/DEVELOPMENT_STATUS.md`, `docs/adr/*.md` (si aplica), `docs/plan_entrega_0.2*.md`
  (si aplica). `src/universal_business/infrastructure/` y `api/` y `verticals/` NO cambian
  salvo `__init__` estrictamente necesarios.

### Test Requirements locales (TR)
- **TR-T7-R1 [rule]:** pytest 0 fallos.
- **TR-T7-R2 [rule]:** ruff check All checks passed.
- **TR-T7-R3 [rule]:** ruff format 0 cambios.
- **TR-T7-R4 [rule]:** mypy Success: no issues found.
- **TR-T7-R5 [rule]:** git diff --check 0 errores.
- **TR-T7-R6 [rule]:** `git diff master...HEAD --name-only -- src/universal_business/infrastructure`
  devuelve vacío o SOLO `__init__.py`.
- **TR-T7-R7 [rule]:** `git diff master...HEAD --name-only -- src/universal_business/api` ídem.
- **TR-T7-R8 [rule]:** grep prohibidos en application: 0 matches.

### Completion Evidence
Outputs guardados como evidencia en el task review.

---

## Task 8: Commit final + git state clean

**Dependencies:** T7 PASS.  **Priority:** high.

### Scope
- `git add .`
- `git commit -m "feat(application): establish Gate 0.2 foundation layer"`
- Confirmar `git status` clean, working tree sin archivos sin commit.

### Test Requirements locales (TR)
- **TR-T8-R1 [rule]:** commit 1 solo al final (o commits serializados coherentes; no merge).
- **TR-T8-R2 [rule]:** `git log --oneline -1` empieza por el mensaje especificado.
- **TR-T8-R3 [rule]:** working tree clean después de commit.

### Completion Evidence
`git status`, `git log --oneline -10` imprimidos en reporte.

---

## Task 9: Review independiente + informe final 17 campos (§26 del usuario)

**Dependencies:** T8 PASS.  **Priority:** high.

Scope: Fase Review de Spec Mode. Generar informe exacto §26 en lenguaje natural español,
con 17 items (Branch actual, Baseline SHA, HEAD SHA, Archivos añadidos, Archivos modificados,
Contratos implementados, Decisiones arquitectónicas, Tests añadidos, Total tests passed,
Ruff result, Ruff format result, Mypy result, Runtime deps before/after, Architecture rules
añadidas, Scope deviations, Deferred work, Gate 0.2 verdict).

Status: pending.

---

## Mapa AC → Task coverage

| Criterio aceptación | Cubre task |
|---|---|
| AC-R-01..03 Messaging / Handlers | T1 |
| AC-R-04 UoW Protocol | T2 |
| AC-R-05 Idempotency Protocol | T2 |
| AC-R-06 Dispatcher / handlers events | T3 |
| AC-R-07 EventPublisher | T3 |
| AC-R-08..09 UseCase / Vertical | T4 |
| AC-R-10 imports innombrables application | T5 |
| AC-R-11 runtime dependencies [] | T7 |
| AC-R-12 AT-1..AT-9 | T5 + T7 |
| AC-R-13..20 AT-10..AT-17 | T5 |
| AC-R-21..25 pytest/ruff/format/mypy/diff | T7 |
| AC-R-26..29 semántica transaction / events / idempotency tests | T2 + T3 + T4 |
| AC-R-30 DEVELOPMENT_STATUS.md actualizado | T6 |
| AC-R-31 commit final + clean | T8 |
| AC-E-01..03 Rubrics quality | T9 Review |
