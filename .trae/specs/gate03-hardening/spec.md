# Especificación — Hardening Final Gate 0.3 Catalog & Resources

## 0. Contexto y objetivo

HEAD actual: `11734062112707df036ec0211f9acf9c3022a0a0` sobre rama `feat/fase-2-catalog-resources`,
baseline `master @ c6a4327`. Gate 0.3 fue consolidado pero presenta 7 hallazgos que deben ser
corregidos sin ampliar scope, sin iniciar Gate 0.4, sin tocar master y sin añadir
infraestructura / API / dependencias runtime.

Objetivo: corregir semántica de idempotencia (pre-commit complete), contrato de queries,
uso de asserts para flujos de negocio, aislamiento tenant+business, dependencias de
constructors sin uso, accuracy de documentación, y añadir tests específicos que
demuestran el orden correcto de los eventos de commit y completado de idempotencia.

## 1. Restricciones no negociables

(Se heredan tal cual del Gate 0.3 §0; se resaltan las más relevantes para hardening:)

1. No tocar master. No merge a master. No tags / releases. No PyPI.
2. Scope Gate 0.3 exclusivo. NO Orders / Reservations / Availability Engine.
3. `dependencies = []` en `pyproject.toml`; sin nuevos runtime packages.
4. Mypy strict intacto. Ruff check + format PASS.
5. Architecture tests AT-1..AT-22 intactos y PASS.
6. Execute_use_case (Foundation Gate 0.2) sigue siendo el único lugar donde se
   hace `uow.commit()`; ningún handler puede invocar commit por sí mismo.
7. Ninguna mutación cross-tenant ni cross-business debe ser posible.
8. Todo `Resource` creado debe apuntar a un `ResourceType` existente dentro del
   mismo tenant/business; si el ResourceType no existe, no se crea el recurso
   huérfano y se levanta `ApplicationError` (decisión arquitectónica por
   consistencia; la semántica "soft" era incorrecta).

## 2. Hallazgos y requisitos funcionales

### H1. Idempotency: complete MUST suceder SOLO después de commit exitoso

**Problema actual:** los cuatro handlers de create (`CreateOfferingHandler`,
`CreateCatalogCategoryHandler`, `CreateResourceTypeHandler`, `CreateResourceHandler`)
invocan `IdempotencyStore.complete(...)` dentro de `handle()`, es decir,
antes de que `execute_use_case` haga `uow.commit()`. El orden observado es:

```
reserve → save → complete(DONE) → return → execute_use_case.commit()
```

Esto permite el escenario roto:

```
reserve OK → save OK → complete(key, DONE) → commit FALLA → release NO ocurre
(ya que complete ya marcó DONE).
```

Resultado: la clave queda `DONE` en el store pero la transacción nunca se
consolidó en el repositorio / UoW. La segunda invocación con la misma key
devuelve un "resultado almacenado" que en realidad nunca existió.

**Requisito funcional R1:** Introducir un hook de post-commit (en
`execute_use_case` o en un pequeño ayudante de composición compatible con
Foundation) de manera que el orden estricto sea:

```
reserve → handler.handle() → uow.commit() → complete → dispatch → publish
```

Reglas de fallback:
- Si `handler.handle()` lanza → `release(key)`.
- Si `uow.commit()` lanza → `release(key)`.
- `complete` nunca ocurre antes de que `commit()` retorne sin excepción.
- Si la key ya estaba `DONE` por una ejecución previa, se devuelve el
  resultado previamente almacenado sin tocar domain/repository (path de
  idempotencia DONE).

---

### H2. Query Handler Contract Consistency

Contrato Gate 0.2 `QueryHandler[InT, OutT]`: `handle(query) -> OutT`,
es decir, resultado directo. Las queries no generan `DomainEvent` y no siguen
el contrato `UseCaseHandler` de mutación.

**Problema actual inconsistente:**
- Resources QueryHandlers (GetResource, ListResourcesByBusiness, etc.) devuelven
  `Resource | None` / `list[Resource]` directo — ✅ cumplen QueryHandler.
- Catalog QueryHandlers (GetOffering, ListOfferingsByBusiness,
  ListOfferingsByLocation, ListActiveOfferings, ListCategoriesByBusiness)
  devuelven `tuple[Result, []]` — ❌ viola contrato QueryHandler.

**Requisito funcional R2:** Cambiar firma y cuerpo de los 5 Catalog
QueryHandlers para devolver `ResultT` directamente. Actualizar typing de
return y tests correspondientes. Mantener CommandHandlers con tupla
`(result, Sequence[DomainEvent])`.

---

### H3. Eliminar asserts para condiciones not-found / negocio

En `ActivateResourceHandler`, `DeactivateResourceHandler`, `ArchiveResourceHandler`,
`AssignResourceToLocationHandler` existe:

```python
assert r is not None, "Resource no encontrado"
```

Esto es inválido como gestión de errores de aplicación: `python -O` elimina
asserts y el código subsiguiente rompe con AttributeError.

**Requisito funcional R3:** Sustituir todos esos asserts por:

```python
if r is None:
    raise ApplicationError(f"Resource {command.resource_id} not found")
```

Aplicar también a cualquier otro equivalente de Catalog que utilice assert para
flujos de aplicación. Añadir tests not-found específicos.

---

### H4. Business Isolation explícito + ResourceType inexistente → error

Hoy existe solo `_assert_same_tenant(...)`. Pero la combinación `tenant_id ==
command.tenant_id` NO es suficiente: también hay que comprobar `business_id ==
command.business_id` (tenancy + ownership de unidad de negocio).

**Requisito funcional R4a:** Crear helper común (ubicado en un módulo compartido
de aplicación o en cada package como helper interno, manteniendo dependencias
circulares a cero) con la firma:

```python
def _assert_same_scope(
    entity_tenant_id: TenantId,
    entity_business_id: BusinessId,
    command_tenant_id: TenantId,
    command_business_id: BusinessId,
    *,
    entity_label: str = "entity",
) -> None: ...
```

Levanta `ApplicationError` con mensaje claro si falla tenant, business o ambos.

Aplicar el helper a TODO handler de mutación tanto en Catalog como en Resources.

**Requisito funcional R4b:** En `CreateResourceHandler`, si `resource_type_repo.get(...)`
devuelve `None` (ResourceType no existe para ese tenant/business), **levantar**
`ApplicationError("ResourceType {id} not found for tenant/business")` y NO
crear el Resource huérfano.

Añadir tests: cross-tenant denied, cross-business denied, same tenant same
business allowed, ResourceType inexistente → error.

---

### H5. Limpiar dependencias de constructor sin uso

Muchos handlers en `application/resources/handlers.py` declaran en `__init__`
parámetros (`uow`, `idempotency_store`, `resource_type_repo`, `resource_repo`)
que luego **nunca se usan** en su método `handle(...)`. Ejemplos:

- `ActivateResourceHandler.__init__` recibe `uow`, `idempotency_store`,
  `resource_type_repo` pero solo usa `resource_repo.get(...)` + `.save(...)`.
- `GetResourceHandler.__init__` recibe 4 params pero solo usa `resource_repo`.
- `ListResourceTypesByBusinessHandler.__init__` recibe `resource_repo` nunca usado.

**Requisito funcional R5:** Para cada handler, mantener en el constructor
ÚNICAMENTE los ports / dependencias que realmente son leídas dentro de
`handle()`. No introducir frameworks DI. Mantener simple: `__init__(self, *, x, y)`
con la lista mínima.

---

### H6. Documentación accuracy

**R6a — Eventos:** Corregir cualquier recuento que indique "14 events" a "12 events"
(6 catalog + 6 resources). Enumerar explícitamente:

Catalog events (6): OfferingCreated, OfferingActivated, OfferingDeactivated,
OfferingArchived, OfferingPriceChanged, CatalogCategoryCreated.

Resources events (6): ResourceTypeCreated, ResourceCreated, ResourceActivated,
ResourceDeactivated, ResourceArchived, ResourceAssignedToLocation.

**R6b — UnitOfWork ownership:** Corregir cualquier afirmación en docs o
docstrings del tipo "Todos los handlers usan UnitOfWork context-manager" por
la realidad: "El UnitOfWork pertenece al orquestador `execute_use_case` de la
capa de ejecución; los handlers NO entran ni salen del UoW. Los handlers
tampoco invocan `uow.commit()`. El commit es exclusivo de `execute_use_case`."

Aplicar correcciones en: `docs/DEVELOPMENT_STATUS.md`, `docs/ARCHITECTURE.md`,
`docs/plan_entrega_0.3_catalog_resources.md` y docstrings de handlers si
corresponde.

---

### H7. Tests específicos que demuestran orden idempotency+commit

Añadir un conjunto de tests que específicamente demuestren que:

- **R7a:** `reserve → handler OK → commit OK → complete` se cumple (complete NUNCA
  antes). Para demostrar, usar un orden de llamadas monitoreado sobre un
  `FakeUnitOfWork` + `FakeIdempotencyStore` con flags / timeline de llamadas.
- **R7b:** `reserve → handler FAIL → release` ocurre, y `complete` es nunca llamado.
- **R7c:** `reserve → handler OK → commit FAIL → release` ocurre, y `complete`
  es nunca llamado.
- **R7d:** Si `commit()` falla, events NUNCA son `dispatch` ni `publish`.
- **R7e:** Ejecución duplicada de una key DONE devuelve el resultado previo
  sin llamar a `repository.save(...)`.
- **R7f:** cross-tenant mutation denied, cross-business mutation denied.
- **R7g:** ResourceType inexistente al crear Resource → ApplicationError.

---

## 3. Criterios de aceptación (ACs — rule/rubric)

| ID | Tipo | Enunciado |
|---|---|---|
| AC1 | rule | execute_use_case u orden equivalente produce `IdempotencyStore.complete()` **SOLAMENTE** si y solo si `UnitOfWork.commit()` ha terminado sin excepción. Se demuestra con un test cronológico (timeline de llamadas). |
| AC2 | rule | En path de handler FAIL, el handler llama a `release()` y nunca a `complete()`. |
| AC3 | rule | En path de commit FAIL, `execute_use_case` ejecuta `release()` y nunca llama a `complete()`, nunca `dispatch/publish` events. |
| AC4 | rule | Los 5 Catalog QueryHandlers devuelven `ResultT` directamente (no tupla). Sus typing annotations reflejan eso. `mypy strict` pasa. |
| AC5 | rule | Todos `assert r is not None` / asserts aplicativos en Catalog/Resources handlers han sido sustituidos por `ApplicationError`. Se añadió al menos un test not-found por categoría. |
| AC6 | rule | Existe helper `_assert_same_scope` que verifica tenant_id AND business_id. Aplicado a TODOS los mutations de Catalog + Resources. |
| AC7 | rule | CreateResourceHandler: si resource_type_repo devuelve None → ApplicationError. No se instancia Resource, no se llama a save. |
| AC8 | rule | Tests: cross-tenant denied; cross-business denied; same tenant + same business allowed. Todos PASS. |
| AC9 | rule | Cada handler constructor recibe únicamente las dependencias que realmente lee dentro de `handle()`. (Se comprueba AST o usage analysis: no self.X declarado sin self.X lectura en handle.) |
| AC10 | rule | Recuento events en DEVELOPMENT_STATUS.md, ARCHITECTURE.md, plan 0.3: catalog 6 + resources 6 = total 12. |
| AC11 | rule | Docstring/afirmaciones sobre UoW no atribuyen al handler el uso del context-manager ni el commit; solo `execute_use_case`. |
| AC12 | rule | `python -m pytest -q` exit 0. Total tests >= 572. |
| AC13 | rule | `ruff check .` 0 errores. `ruff format --check .` 0 reformats. |
| AC14 | rule | `mypy src` strict 0 errores. |
| AC15 | rule | `git diff --check` 0 whitespace errors. |
| AC16 | rule | Scope audit: cambios únicamente en docs/, src/universal_business/{application,domain}/, tests/, .trae/specs/gate03-hardening/. Ninguno en infrastructure/, api/, verticals/. |
| AC17 | rule | `dependencies = []` en pyproject.toml intacto (sin runtime packages). |
| AC18 | rule | AT-1..AT-22 intactos PASS. |
| AC19 | rule | Commit único con mensaje exacto: `fix(catalog): harden Gate 0.3 transaction and scope semantics`. Push a origin `feat/fase-2-catalog-resources` exit 0. |
| AC20 | rubric | Workflow fidelity (escala 0-2): 2 si phases spec→plan→implement→review→quality gate seguidos con boundaries; 1 con 1 error non-critical; 0 si hay review dependency collapse o omisión artifacts. |
| AC21 | rubric | Adaptabilidad (0-2): 2 si implementación H1 preserva Foundation Gate 0.2 UseCaseHandler sin romper handlers existentes; 1 si se rompió algo y se reparó; 0 si reescritura grande de execute_use_case sin compatibilidad. |

## 4. Suposiciones

- Se permite extender `UseCaseHandler` con un método opcional (`post_commit(result)
  -> None` o un hook con nombre similar) para que los handlers que necesitan
  post-commit lo implementen y `execute_use_case` lo invoque. Los handlers
  existentes que no implementan el hook siguen funcionando sin cambios.
- `IdempotencyStore.reserve()` sigue siendo positional-only.
- Para R7 (tests cronológicos), se permite un `FakeUnitOfWork` con un contador
  `commit_called: bool` y `commit_raises: Exception | None`; y un
  `FakeIdempotencyStore` que anota un timeline tipo list[str] de operaciones
  con timestamps secuenciales.
- No se añade ni un solo archivo fuera del scope de hardening.
