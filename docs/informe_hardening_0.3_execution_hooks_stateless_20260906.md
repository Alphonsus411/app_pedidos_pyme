# Informe — Hardening Final Execution Hooks Stateless Gate 0.3

- **Fecha emisión:** 2026-09-06
- **Rama origen:** `feat/fase-2-catalog-resources`
- **Commit SHA aplicado (local = remoto):** `a478e3f7cf69ab9311c2dc7698f6b31a4f3204a8`
- **Commit mensaje exacto:** `fix(application): make Gate 0.3 execution hooks stateless`
- **Baseline Gate 0.3 anterior:** `84060c9f638f7196e59606cf231653e62cce8210`
- **Rama master (NO tocada):** `c6a43275a834bf511afcf28c8673d4345c110006`
- **Trae Spec asociada activa:** `.trae/specs/gate03-hardening/`
- **Traza histórica hardening Gate 0.3 previa:** commit `84060c9…` (`fix(catalog): harden Gate 0.3 transaction and scope semantics`)
- **Scope:** NO Gate 0.4. NO infra/API/verticales. NO nuevas deps.

---

## 1. Resumen Ejecutivo

Segundo round de hardening Gate 0.3 sobre los 4 Create handlers idempotentes. Dos problemas arquitectónicos quedaban pendientes tras el primer hardening 84060c9:

1. **Contract Protocol erróneo** — `UseCaseHandler` Protocol incluía los dos hooks (`post_commit_success` / `post_rollback`) aunque se documentaban como *opcionales*. En structural typing esto los convertía en métodos REQUERIDOS para todo handler.
2. **Estado mutable compartido por instancia** — los 4 Create handlers guardaban el "pendiente idempotencia" en `self._idem_pending = (store, tid, key, digest, result)`. Dos `execute_use_case` concurrentes sobre LA MISMA instancia handler corrompían la reserva/complete/release de la otra ejecución.
3. **Complete failure semantics débil** — el código borraba `_idem_pending = None` ANTES de invocar `store.complete()`. Si complete lanzaba, perdíamos el rastro y podríamos invocar release erróneamente permitiendo un duplicado.

Se aplica refactor stateless per-execution. QA pipeline completo: 646 tests PASS / ruff 0 / mypy 0 / format 0 / ATs 352 PASS / deps=[] / git diff check 0. Push origin confirmado SHA remoto == local.

---

## 2. Hallazgos corregidos (P1..P5)

### P2. Optional Hook Protocol Contract ✅

**Sede código:** [execution/__init__.py](file:///c:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/src/universal_business/application/execution/__init__.py#L110-L222)

Se restablece la regla Gate 0.2: **`UseCaseHandler` Protocol SÓLO exige `handle(input) -> tuple[OutT, Sequence[DomainEvent]]`**. Los hooks (si existen) viven en Protocolos auxiliares separados `@runtime_checkable`:

| Protocol | Varianza typing | Contenido |
|---|---|---|
| `UseCaseHandler[InT, OutT_co]` | InT **contravariant**; OutT_co **covariant** | `handle(input, /) -> tuple[OutT_co, Sequence[DomainEvent]]` |
| `PostCommitSuccessHook[OutT_contra]` @runtime_checkable | OutT_contra **contravariant** | `post_commit_success(self, result: OutT_contra, /) -> None` (compat legacy) |
| `PostRollbackHook` @runtime_checkable | invariant | `post_rollback(self, exc: BaseException, /) -> None` (compat legacy) |
| `UseCaseHandlerWithExecutionHooks[InT, OutT]` @runtime_checkable | invariant | `handle(...)` + **`build_hooks(input, result, /) -> ExecutionHooks[OutT] \| None`** (STATLESS nuevo pattern) |

`execute_use_case` detecta hooks por **`isinstance(handler, UseCaseHandlerWithExecutionHooks)`** runtime_checkable; fallback a Protocols legacy para backward compat con handlers aún no migrados (ninguno actual; los 4 Creates migran a build_hooks). Handlers sin hooks (todos non-create + todas queries) SATISFACEN `UseCaseHandler` sin declarar métodos extra.

---

### P3. Remove mutable per-execution state — ExecutionHooks INMUTABLE per-ejecución ✅

**SEDES:**
- [execution/__init__.py: ExecutionHooks + IdempotencyExecutionState frozen](file:///c:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/src/universal_business/application/execution/__init__.py#L62-L107)
- [catalog/handlers.py: CreateOffering + CreateCategory build_hooks](file:///c:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/src/universal_business/application/catalog/handlers.py#L91-L216)
- [resources/handlers.py: CreateResourceType + CreateResource build_hooks](file:///c:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/src/universal_business/application/resources/handlers.py)

#### Eliminado
El atributo mutable por instancia `self._idem_pending: tuple[Store, Tid, Key, Digest, Result] | None` que era fuente de race conditions. **4 handlers** migrados.

#### Sustituido por
Dos dataclasses `frozen=True` (inmutables) VIVEN por ejecución, NO por handler:

```python
@dataclass(frozen=True)
class IdempotencyExecutionState:
    store: IdempotencyStore
    tenant_id: TenantId
    idempotency_key: IdempotencyKey
    result_digest: str
    result_for_complete: object | None = None

@dataclass(frozen=True)
class ExecutionHooks[OutT]:
    on_success: Callable[[OutT], None] | None = None
    on_failure: Callable[[BaseException], None] | None = None
```

#### Flujo STATLESS limpio
1. `execute_use_case` llama `result, events = handler.handle(input)` dentro de `with uow:`.
2. Inmediatamente DESPUÉS (aún dentro `with uow`, ANTES de `uow.commit`) — si isinstance build_hooks:
   `hooks = handler.build_hooks(input, result)`
3. `hooks` contiene **closures / functools.partial** que capturan `(store, tid, key, digest, result)` como variables locales **por-ejecución**. Nada se escribe en `handler`.
4. **Dentro try/except uow.commit:**
   - Si commit lanza → `hooks.on_failure(exc)` → `store.release(tid, key)`.
   - Si commit OK → afuera del `with uow` → `hooks.on_success(result)` → `store.complete(tid, key, digest, result)`.
5. Cada invocación crea closures DIFERENTES. Reutilización concurrente handler no comparte nada.

#### Gap cerrado: try/except release INTERNO en handle()
Había un hueco: `store.reserve()` ejecuta OK dentro de handle pero el resto de handle() lanza (validación de Money, ResourceType not found, save repo explota). En ese escenario `handle()` no retorna. `execute_use_case` nunca entra a `build_hooks`; la key quedaba RESERVED leak indefinido.

Solución STATLESS: **cada create handler 4x** tiene un `try / except BaseException` en `handle()`:
- Flag `reserved_flag: bool = False` se pone `True` si `store.reserve(...)` retornó True.
- Si cualquier excepción ocurre DESPUÉS de reserve y ANTES del return:
  `if reserved_flag and id_key is not None: store.release(tid, id_key)`
- Re-raise la excepción original (transparente para el caller).

Esto garantiza que key RESERVED sin `build_hooks` ejecutado se libera inmediatamente sin depender del orquestador ni de hooks structural. Ningún leak.

---

### P4. Complete Failure Semantics (complete falla POST-COMMIT) ✅

**Sede:** [execute_use_case post-commit zone](file:///c:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/src/universal_business/application/execution/__init__.py#L292-L340)

Reglas implementadas (matching requisito usuario):

| Caso | Dominio | Idempotency key | Events | Error propagado |
|---|---|---|---|---|
| uow.commit falla | rollback (UoW cm) | release llamado vía on_failure | NUNCA publicados | exc original |
| commit OK + complete OK | committed | RESERVED → DONE | dispatch + publish OK | no |
| commit OK + complete FALLA | **committed NO rollback** | **permanece RESERVED. NO release.** | **SÍ fluyen** (son parte del dominio confirmado) | **hook_exc propagado UP** |

#### Documentación de semántica
Incluida en docstring execute_use_case líneas 261-290 execution/__init__.py:
> ### Complete failure (post-commit indeterminacy)
> NO existe atomicidad cross-system entre `uow.commit()` (DB dominio) y `store.complete()` (IdempotencyStore — Redis/SQL/otro). El diseño elige: SEGURIDAD SOBRE DUPLICADOS > simular atomicidad falsa. Si complete lanza:
> - Dominio committeado queda. Rollback imposible fuera tx.
> - Key NO se libera (permanece RESERVED) para que una segunda ejecución no entre y cree un duplicado.
> - Events SÍ se publican (son un output derivado del dominio confirmado).
> - Excepción se propaga. Monitorea; reconciliación manual futura cuando sea necesaria.
> - NO implementamos Outbox, compensating transactions ni persistence dedicated reconciliation now.

#### Orden operaciones
Se garantiza **primero complete()**, después (implicitamente) las variables del closure mueren al salir de scope. Nunca "borrar el estado ANTES de llamar complete". En dataclass frozen + closures no hay state mutable que borrar, por lo que el bug clase `self._idem_pending = None; store.complete(...)` queda imposible.

---

### PRESERVAR intactos (Requisito 4)
| Item | Sede confirmada |
|---|---|
| Catalog QueryHandlers → `Offering \| None` / `list[Offering]` / `list[CatalogCategory]` directo | catalog/handlers.py queries (5 handlers intactos) |
| Resources not-found → ApplicationError (no assert) | resources/handlers.py Activate/Deactivate/Archive/Assign |
| `_assert_same_scope` cross-tenant + cross-business en todas mutaciones | catalog y resources handlers |
| ResourceType missing → ApplicationError (no Resource huérfano) | CreateResourceHandler.handle early return |
| Constructor deps minimizadas (sólo ports usados por handler) | resources handlers constructores |
| `dependencies = []` en pyproject.toml runtime | verify salida command |
| AT-1..AT-22 architecture tests PASS | tests/architecture/test_architecture_boundaries.py 352 tests |
| Python 3.11 + 3.12 / mypy strict compatible | type vars variantes correctos |
| NO infrastructure / API / verticales / Orders / Reservations / Availability | grep scope audit anterior intact |

---

## 3. Tests Nuevos & Legacy adaptados

**Sede tests actualizados:** [test_execution_idempotency_hooks.py](file:///c:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/tests/unit/test_execution_idempotency_hooks.py)

### Tests NUEVOS añadidos (6):
| ID | Nombre test | Propósito |
|---|---|---|
| (a) | `test_stateless_handler_two_concurrent_executions_independent_keys` | Handler singleton reutilizado, 2 execute_use_case con keys A y B. Timeline A: reserve_A / commit / complete_A; Timeline B igual; NO interferencia; keys correctas en cada complete |
| (b) | `test_stateless_handler_rollback_a_no_release_b` | Ejecución A: `FakeUoW.commit_raises = RuntimeError("db down")` → `release_A llamado`. Ejecución B: success → `complete_B llamado`. release NO liberó key B. |
| (c) | `test_stateless_handler_commit_a_no_complete_b` | Secuenciales A→B success; complete_A y complete_B ambas invocadas con `(tenant_id, key_A/digest_A/Offering_A)` y `(tenant_id, key_B/digest_B/Offering_B)` correctas |
| (d) | `test_stateless_reuse_handler_no_pending_state` | Handler 2 usos; antes del 2º uso `hasattr(h, "_idem_pending") == False`. Segundo uso devuelve Offering nuevo sin errores |
| (e) | `test_non_create_handler_no_build_hooks_method` | `isinstance(ActivateOfferingHandler(...), UseCaseHandlerWithExecutionHooks) == False`; isinstance PostCommitSuccessHook == False; activate funciona normal events correctos |
| (f) | `test_complete_failure_after_commit_no_release` | FakeIdempotencyStore con `complete_raises = RuntimeError("idem-db gone")` → verify: uow.commit_called=True; store.release_called_count == 0; dispatch ≥1; publisher ≥1; `pytest.raises(RuntimeError)` outer match "idem-db" |

### Legacy tests adaptados (3) en test_application_resources.py:
- `test_create_resource_type_happy_idempotency_done` → reemplazada llamada manual `h.post_commit_success(result)` por `h.build_hooks(cmd, result).on_success(result)` correcto.
- `test_create_resource_type_duplicate_key_then_noop` → igual build_hooks.
- `test_rollback_on_repository_error` → NO manual `h.post_rollback(e)`; el release ahora ocurre vía try/except INTERNO dentro handle. Verifica `store.release_called_count == 1` sin necesidad de llamadas hooks.

---

## 4. Pipeline QA — Full PASS

| Step | Resultado |
|---|---|
| `python -m pytest` | ✅ **646 passed** (6 tests nuevos + 6 actualizados legacy; diff +6 vs hardening 84060c9) |
| `ruff check .` | ✅ All checks passed! 0 errores |
| `ruff format --check .` | ✅ 99 files already formatted (3 reformatted post-subagent → aplicados) |
| `mypy src` | ✅ Success: no issues found in 71 source files (strict mode, strict-equality, strict-optional, warn-return-any, ignore-missing-imports off para stdlib) |
| `git diff --check` | ✅ exit 0 (0 whitespace issues) |
| dependencies runtime pyproject | ✅ `[]` verified via tomllib |
| Architecture tests AT-1..AT-22 | ✅ 352 tests PASS 100% |
| Scope audit forbidden dirs | ✅ 0 archivos en infrastructure/, api/, verticals/ |
| Working tree post-commit | ✅ clean (`git status` nada que commitear) |
| Remote sync | ✅ git rev-parse HEAD == git ls-remote → both `a478e3f…` |

---

## 5. Trazabilidad git

```
master c6a43275...  (baseline sin gate 0.3)
  \ feat/fase-2-catalog-resources
    \ 117340621... (Gate 0.3 consolidated feat(catalog): establish Gate 0.3...)
     \ 84060c9...  (Hardening 1 fix(catalog): harden Gate 0.3 transaction and scope semantics)
      \ a478e3f... (Hardening 2 fix(application): make Gate 0.3 execution hooks stateless) ← HEAD ahora
```

Commandos QA ejecutados reproducibles:

```powershell
cd c:\Users\Adolfo\PycharmProjects\app_pedidos_pyme
python -m pytest -q                    # 646 passed, 1 warning
ruff check .                           # All checks passed!
ruff format . ; ruff format --check .  # 99 files already formatted
mypy src                               # Success 71 source files
git diff --check                       # exit 0
git add .
git commit -m "fix(application): make Gate 0.3 execution hooks stateless"
git push origin feat/fase-2-catalog-resources
```

---

## 6. Gate Verdict

**🟢 HARDENING EXECUTION HOOKS GATE 0.3 — PASS**

| Criterio | Cumplimiento |
|---|---|
| Protocol hooks opcionales NO requeridos en UseCaseHandler | ✅ |
| Handlers sin hooks satisfacen UseCaseHandler Protocol | ✅ isinstance + tests (e) |
| Mutable shared _idem_pending eliminado de 4 creates | ✅ hasattr False |
| ExecutionHooks frozen inmutable per-ejecución | ✅ closures capturan state sin tocar self |
| 2 ejecuciones concurrentes handler = independientes timeline | ✅ test (a)(b)(c) |
| Reutilización secuencial handler = sin leak/state colgado | ✅ test (d) |
| Rollback de A → NO release de key B (cross) | ✅ test (b) |
| Commit A → NO complete con key B | ✅ test (c) assertions |
| Complete falla → dominio committed, NO release, events sí, error propaga | ✅ test (f) |
| Preservación fixes hardening anteriores 84060c9 | ✅ ResultT / AppError / scope / RT missing |
| dependencies = [] / sin infra/api/verticals/orders | ✅ audit |
| ATs architecture 352 PASS | ✅ |
| Full pipeline 646 / ruff / mypy / format / diff check | ✅ 0 defects |
| Commit exact message + push remoto == local HEAD SHA | ✅ |

Fin informe.
