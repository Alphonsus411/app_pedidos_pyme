# Tasks — Hardening Gate 0.3 Catalog & Resources

Cada task incluye Test Requirements (TRs), que deben pasar con su evidencia.

## Task 1: Idempotency — post-commit hook en execute_use_case + refactor 4 create handlers
**Prioridad: high**
**Files scope:**
- `src/universal_business/application/execution/__init__.py`
- `src/universal_business/application/catalog/handlers.py` (CreateOffering, CreateCategory)
- `src/universal_business/application/resources/handlers.py` (CreateResourceType, CreateResource)

**Descripción:**
Introducir hook `post_commit(result: OutT) -> None` opcional en el contrato
(UseCaseHandler Protocol: añadir un método con default NotImplementedError o
detectar su presencia con hasattr() en execute_use_case para backwards
compat). Ejecutar `post_commit(result)` DESPUÉS de uow.commit() pero ANTES
de dispatch/publish (o inmediatamente después; la clave es que complete()
ocurra SOLO si commit fue exitoso).

Para los 4 create handlers:
- Antes: complete() se llamaba DENTRO de handle(). → Ahora: handle() NO
  llama a complete(). En su lugar:
  - El handler almacena un estado interno (tupla pendiente: `_pending_idem_complete:
    tuple[IdempotencyStore, TenantId, IdempotencyKey, str, object] | None =
    None`).
  - El handler implementa `post_commit(result)` con el complete; si hubo un
    camino idempotency que devolvió cached_result sin trabajo, no hay
    post_commit (no hay nada que hacer, ya estaba complete).
- En handle() path normal: almacenar pendiente, NO llamar complete.
- En handle() path cached: devolver (cached, []) sin tocar store (ya estaba).
- El rollback via release queda en el try/except INTERNO del handler? — NO:
  porque ahora commit puede fallar fuera del handler. Hay que mover también
  el release al post_failure hook? Mejor: el execute_use_case con post_commit
  puede ofrecer también un hook `on_rollback(exc: BaseException) -> None`
  para que el handler haga release SI:
  - Handler reservó (estado pendiente de reserve)
  - O bien, el execute_use_case captura todo el flujo try/around:
    reserve_handler antes? No, reserve está en handle.
    Mejor alternativa simple: execute_use_case NO hace reserve. Reserve queda
    en handler.handle(). El handler.set_pending() marca "si falla, hay que
    release". execute_use_case necesita además un hook
    `on_failure(exc)` en UseCaseHandler que se invoca si handle o commit
    lanzan (o al salir del with exc on).

Alternativa más simple y explícita (mínima, sin cambiar UseCaseHandler Protocol
fuerte): El execute_use_case acepta un callback `on_success:
Callable[[OutT],None] | None` y `on_failure:
Callable[[BaseException],None] | None` opcionales kwargs-only. Pero los
handlers no pasan callbacks al orquestador; el caller (tests o future use case
runner) lo hace. No, queremos que el handler sea quien tenga la semántica.

Solución mínima final (elegida): extender `UseCaseHandler Protocol` con dos
métodos OPCIONALES (tienen implementación default en un MixIn o son detectados
dinámicamente por `execute_use_case` usando `hasattr(handler, "post_commit_success")`
antes de llamarlos):

```
def post_commit_success(self, result: OutT, /) -> None: ...
def post_rollback(self, exc: BaseException, /) -> None: ...
```

execute_use_case (dentro del with unit_of_work): después de handler.handle()
OK, antes de uow.commit, NO hace nada. Después de uow.commit OK (fuera del
with pero antes de dispatch): llama `post_commit_success(result)` si existe.
Si handler.handle() lanza o commit lanza: al salir del with (con exc=True),
llama a `post_rollback(exc)` si existe (antes de propagar). El use case
handlers Create implementan ambos hooks (post_commit_success → complete;
post_rollback → release si hubo reserva y no se completó).

Los handlers almacenan: `_idem_pending: tuple[store, tid, key, digest, result]
| None = None` (en `handle` se setea; en `post_commit_success` se consume
haciendo `complete`; en `post_rollback` se consume haciendo `release`).

**Test Requirements:**
- TR1.1 [rule] Un `FakeIdempotencyStore` con timeline `list[("op" str, "order"
  int)]` muestra que el orden es `reserve → handle_OK → commit → complete`.
  Ej: timeline = [("reserve", 1), ("commit", 2), ("complete", 3)]. NO
  existe complete antes de commit.
- TR1.2 [rule] Cuando `FakeUnitOfWork.commit()` lanza `RuntimeError("boom")`:
  timeline contiene `[("reserve", 1), ("release", 2)]`. No aparece
  `complete`. No hay dispatch ni publish.
- TR1.3 [rule] Cuando handler.handle levanta ApplicationError durante save
  simulado: timeline `reserve → release`. No complete.
- TR1.4 [rule] Call 2da idempotente id_key DONE: handler devuelve resultado
  almacenado sin llamar `repository.save()`, sin llamar `commit()` (puede
  que sí llame a commit? No, sí debería pero sin trabajo). En todo caso,
  timeline NO tiene un 2º complete (ya era DONE; se devuelve sin reservar).
- TR1.5 [rubric 0-2] Execute_use_case backwards-compatible con handlers no
  create que no implementan hooks: 2 si pasan sin cambios; 1 si requieren
  cambios mínimos; 0 si se rompen.
**Status:** pending

---

## Task 2: Catalog QueryHandlers contrato QueryHandler ResultT
**Prioridad: high**
**Files scope:**
- `src/universal_business/application/catalog/handlers.py` (5 query handlers)
- `tests/unit/test_application_catalog.py` (tests queries existentes y nuevos)

**Descripción:**
GetOfferingHandler: `handle(query) -> Offering | None`.
ListOfferingsByBusinessHandler: `handle(query) -> list[Offering]`.
ListOfferingsByLocationHandler: `handle(query) -> list[Offering]`.
ListActiveOfferingsHandler: `handle(query) -> list[Offering]`.
ListCategoriesByBusinessHandler: `handle(query) -> list[CatalogCategory]`.

Eliminar `Sequence[DomainEvent]` de sus returns y devolver directamente el
resultado. Actualizar tests que esperaban tupla.

Si se usa `execute_use_case` para queries (no es habitual), las queries NO
pasarán por execute_use_case (porque no cumplen UseCaseHandler Protocol).
Se ejecutarán directamente (es correcto; queries no transaccionalizan).

**Test Requirements:**
- TR2.1 [rule] mypy strict pasa (0 errores typing queries).
- TR2.2 [rule] Todos los tests existentes de catalog queries que esperaban
  `result, _ = handler.handle(q)` → ahora son `result = handler.handle(q)`.
- TR2.3 [rule] `QueryHandler[ListOfferingsByBusiness, list[Offering]]`
  contract es estructuralmente compatible con cada Catalog QueryHandler.
**Status:** pending

---

## Task 3: Eliminar asserts applicativos → ApplicationError (Resources handlers)
**Prioridad: high**
**Files scope:** `application/resources/handlers.py` (Activate/Deactivate/Archive/Assign)

**Descripción:**
4 sitios con `assert r is not None, "Resource no encontrado"` → sustituir por `if r is None: raise ApplicationError(f"Resource {command.resource_id} not found")`.

**Test Requirements:**
- TR3.1 [rule] 4 tests nuevos (uno por handler) que resource_id inexistente →
  `ApplicationError` (no `AssertionError`).
- TR3.2 [rule] `python -O tests/unit/test_application_resources.py` modo
  optimizado no cambia semántica (sigue fallando con ApplicationError; no
  AttributeError por None).
**Status:** pending

---

## Task 4: _assert_same_scope helper + cross-business isolation + ResourceType required
**Prioridad: high**
**Files scope:**
- `application/resources/handlers.py`: añadir `_assert_same_scope`. Aplicar a
  mutaciones. Validar resource_type existe al crear Resource → ApplicationError.
- `application/catalog/handlers.py`: añadir `_assert_same_scope`. Aplicar a
  todas mutations (ActivateOffering, DeactivateOffering, ArchiveOffering,
  ChangeOfferingPrice, CreateOffering si existiera, CreateCategory — cross
  business implica comprobar también business_id de existing contra command).

**Descripción:**
Firma helper:
```python
def _assert_same_scope(
    entity_tenant_id: TenantId,
    entity_business_id: BusinessId,
    command_tenant_id: TenantId,
    command_business_id: BusinessId,
    *,
    entity_label: str = "entity",
) -> None:
```
Si falla tenant: mensaje "Cross-tenant mutation DENIED..." ApplicationError.
Si falla business (tenant correcto pero business !=): mensaje
"Cross-business mutation DENIED... pertenece a business B y command usa business
C." ApplicationError.
Ambos fallos → ApplicationError.

CreateResource: Si `resource_type_repo.get(...)` devuelve None →
`ApplicationError(f"ResourceType {command.resource_type_id} not found for
tenant/business")`.

**Test Requirements:**
- TR4.1 [rule] cross-tenant denied test existe para Catalog Offering mutación
  y Resources mutación (2 tests).
- TR4.2 [rule] cross-business same-tenant denied test existe para Offering
  mutación y Resource mutación (2 tests).
- TR4.3 [rule] same tenant + same business pass test existe para Offering
  mutación y Resource mutación (2 tests).
- TR4.4 [rule] test CreateResource con resource_type_id inexistente →
  ApplicationError; `resource_repo.save()` no se invocó (verificar con FakeRepo
  save_called boolean).
**Status:** pending

---

## Task 5: Clean unused constructor dependencies (Resources handlers)
**Prioridad: medium**
**Files scope:** `application/resources/handlers.py` (__init__ de todos 11 handlers)

**Descripción:**
Para cada handler: recorrer su handle() y anotar todos atributos `self.X` que
lee. Mantener en `__init__` únicamente esos parámetros. Ejemplos:

- `ActivateResourceHandler`: usa `self.resource_repo.get(...)`, `self.resource_repo.save(...)`. No toca resource_type_repo, uow, idempotency_store. Eliminar params.
- `GetResourceHandler`: solo usa `resource_repo`. Eliminar los otros 3.
- `ListResourceTypesByBusinessHandler`: solo usa `resource_type_repo`.
  Eliminar `resource_repo`, uow, idempotency.
- `CreateResourceTypeHandler`: usa `resource_type_repo`, `idempotency_store`.
  NO usa `resource_repo` ni `uow` (el commit lo hace execute_use_case fuera).
  Eliminar.

**Test Requirements:**
- TR5.1 [rule] `ruff check .` sigue 0 errores typing (no hay kwargs
  incompatibles con llamadas existentes en tests de application resources).
- TR5.2 [rule] Todo handler en resources: `any(self.X not in
  {lecturas en handle()})` → 0 coincidencias.
**Status:** pending

---

## Task 6: Docs accuracy (events count 12 + UnitOfWork semantics)
**Prioridad: medium**
**Files scope:**
- `docs/DEVELOPMENT_STATUS.md`
- `docs/ARCHITECTURE.md`
- `docs/plan_entrega_0.3_catalog_resources.md`
- Docstrings `application/catalog/handlers.py`, `application/resources/handlers.py`

**Descripción:**
Corregir recuento events a 12 (6+6) con listado explícito. Corregir frase
"handlers usan UnitOfWork context-manager" por realidad: "UnitOfWork usado
por orquestador execute_use_case; handlers no entran en context manager ni
hacen commit."

**Test Requirements:**
- TR6.1 [rule] Búsqueda `grep -iE "14 events|14 domain" docs/ src/` → 0 hits.
- TR6.2 [rule] Búsqueda `grep -E "UnitOfWork context-manager" src/universal_business/application/catalog/handlers.py src/universal_business/application/resources/handlers.py` → 0 hits si la frase no es correcta; reemplazada por frase exacta.
**Status:** pending

---

## Task 7: Tests específicos commit-fail + idempotency timeline
**Prioridad: high**
**Files scope:**
- `tests/unit/test_application_catalog.py`: añadir tests H7a/H7b/H7c (CreateOffering
  commit fail release, handler fail release, duplicate done no-save).
- `tests/unit/test_application_resources.py`: añadir tests commit-fail,
  handler-fail, ResourceType not-found, cross-business denied.
- NUEVO archivo: `tests/unit/test_execution_idempotency_hooks.py` que centraliza
  timeline de operaciones AC1..AC3 usando FakeUoW+FakeIdemStore +
  CreateOfferingHandler via `execute_use_case`.

**Test Requirements:**
- TR7.1 [rule] AC1 demostrado con timeline: orden `reserve → commit →
  complete` exacto. No "complete → commit".
- TR7.2 [rule] AC2 handler FAIL → release timeline aparece, complete NO.
- TR7.3 [rule] AC3 commit FAIL → release timeline aparece, complete NO.
- TR7.4 [rule] AC4 events no publicados si commit falla (verificar
  FakeEventPublisher.publish_many lista vacía en path commit-fail).
- TR7.5 [rule] AC5 duplicate DONE devuelve resultado previo sin segundo save.
- TR7.6 [rule] AC6 cross-tenant/cross-business denied tests PASS (Task 4).
- TR7.7 [rule] AC7 ResourceType inexistente → ApplicationError (Task 4).
**Status:** pending

---

## Task 8: Quality Gate + commit push exacto
**Prioridad: high**
**Files scope:** repo root, .git

**Descripción:**
Ejecutar §7 validación:
```
python -m pytest -q
ruff check .
ruff format --check .
mypy src
git diff --check
git status
git diff master...HEAD --name-only
```
Confirmar dependencies = []; AT-1..AT-22; sin infrastructure/api/verticals;
sin runtime packages; sin merge/tags.

Commit exacto:
`git add . && git commit -m "fix(catalog): harden Gate 0.3 transaction and scope semantics"`
Push a origin feat/fase-2-catalog-resources.

**Test Requirements:**
- TR8.1 [rule] pytest exit 0, ruff check exit 0, ruff format exit 0, mypy exit
  0, git diff --check exit 0, git push exit 0.
- TR8.2 [rule] `grep -RniE "fastapi|starlette|sqlalchemy|redis|celery|kafka|..."
  src/universal_business` → 0 imports reales (solo comentarios permitidos).
- TR8.3 [rule] Scope audit git diff master...HEAD nombre de archivos: NO
  aparece ningún path que empiece por `infrastructure/`, `api/`, `verticals/`.
- TR8.4 [rule] Commit message exacto coincide cadena del enunciado.
- TR8.5 [rule] Push origin feat/fase-2-catalog-resources exit 0; HEAD remoto =
  HEAD local SHA.
