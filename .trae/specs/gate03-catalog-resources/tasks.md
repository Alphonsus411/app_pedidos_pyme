# Tasks — Gate 0.3 Catalog & Resources

**Spec asociado:** [spec.md](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/.trae/specs/gate03-catalog-resources/spec.md)
**Rama:** `feat/fase-2-catalog-resources`
**Baseline:** `master @ c6a4327`

---

## Task 1: Domain — Nuevos Strong IDs
**Status:** pending
**Priority:** high
**Parent AC:** AC-34 (regla implícita)

### Descripción
Añadir 3 nuevos IDs fuertes a `domain/shared/value_objects/ids.py`:
- `OfferingId(BaseStrongId)`
- `CatalogCategoryId(BaseStrongId)`
- `ResourceTypeId(BaseStrongId)`

Actualizar `__all__`. NO tocar IDs existentes.

### Test Requirements
- **rule TR1.1:** `OfferingId.generate()` devuelve instancia OfferingId.
- **rule TR1.2:** `CatalogCategoryId.generate()` y `ResourceTypeId.generate()` instancias correctas.
- **rule TR1.3:** `from_str` parse desde UUID válido OK; string inválido InvariantViolationError.
- **rule TR1.4:** Nuevos IDs aparecen en `__all__` del módulo ids.py.

---

## Task 2: Domain — Catalog (Offering, CatalogCategory, OfferingResourceRequirement, Events)
**Status:** pending
**Priority:** high
**Parent AC:** AC-1, AC-2, AC-3, AC-6, AC-7, FR-1..FR-12, FR-23, FR-34..FR-40

### Descripción
Modificar `domain/catalog/`:
1. **value_objects.py** → reutilizar `CatalogItemStatus` si coincide; o si se prefiere, mantener para Offering el mismo status (reutilizar). Mantener CatalogItem legacy intacto.
2. **entities.py** → Añadir (no borrar CatalogItem):
   - `Offering(BaseEntity[OfferingId])` frozen? → no, BaseEntity es mutable dataclass kw_only. Métodos: activate(), deactivate(), archive(), change_base_price(new_price). Status: CatalogItemStatus (reutilizar) DRAFT/ACTIVE/INACTIVE/ARCHIVED. Archived NO vuelve ACTIVE/INACTIVE.
   - `CatalogCategory(BaseEntity[CatalogCategoryId])` con validation: self.parent_category_id != self.category_id (si se asigna).
   - `OfferingResourceRequirement` como frozen dataclass: `offering_id: OfferingId`, `resource_type_id: ResourceTypeId`, `quantity_required: int`, `required_flag: bool = True`. Validación: `quantity_required >= 1`.
3. **events.py** (NUEVO ARCHIVO catalog/events.py): OfferingCreated, OfferingActivated, OfferingDeactivated, OfferingArchived, OfferingPriceChanged, CatalogCategoryCreated → todos frozen dataclass(kw_only=True) heredan de DomainEvent. aggregate_type = "Offering"/"CatalogCategory". Llevar tenant_id, business_id obligatorios.
4. **__init__.py catalog**: actualizar exports.
5. **ports.py** → Añadir `IOfferingRepository` y `ICatalogCategoryRepository`. Mantener legacy `ICatalogRepository` intacto.

### Test Requirements
**Offering:**
- **rule TR2.1:** create valid → nombre no vacío, tenant_id + business_id obligatorios OK.
- **rule TR2.2:** name vacío/whitespace → InvariantViolationError.
- **rule TR2.3:** activate/deactivate OK; archive → luego activate → InvariantViolationError.
- **rule TR2.4:** change_base_price (con currency igual) OK emite OfferingPriceChanged.
- **rule TR2.5:** Money float no permitido (heredado Money, pero Offering no acepta float en base_price implícitamente).

**Category:**
- **rule TR2.6:** create valid OK.
- **rule TR2.7:** parent == self (posterior asignación) → InvariantViolationError.
- **rule TR2.8:** tenant/business presence obligatoria.

**OfferingResourceRequirement:**
- **rule TR2.9:** quantity_required > 0 OK; =0 o <0 → InvariantViolationError.

---

## Task 3: Domain — Resources (ResourceType entidad, Resource actualizado)
**Status:** pending
**Priority:** high
**Parent AC:** AC-4, AC-5, AC-6, FR-13..FR-16, FR-34..FR-41

### Descripción
Modificar `domain/resources/`:
1. **value_objects.py** → Mantener `ResourceType(StrEnum)` legacy intacto (para no romper). Mantener `ResourceStatus` actual ACTIVE/INACTIVE/MAINTENANCE/RETIRED. Para el lifecycle nuevo ResourceType/Resource: reutilizar `CatalogItemStatus` o `ResourceStatus` según convenga. **Decisión: Resource entidad usa `ResourceStatus` existente (agregar si falta statuses: ARCHIVED? si no está, añadir ResourceStatus.ARCHIVED = "archived" al ResourceStatus StrEnum).**
2. **entities.py** → Añadir `ResourceType(BaseEntity[ResourceTypeId])` (entidad agregada configurable): resource_type_id, tenant_id, business_id, name, description optional, status=DRAFT por defecto (reutilizar CatalogItemStatus). Métodos activate/deactivate/archive. Eliminar el campo `type: ResourceType` (enum) existente de Resource.
3. **Actualizar Resource entidad existente:**
   - `type: ResourceType` (enum) → CAMBIAR por `resource_type_id: ResourceTypeId`.
   - `location_id: LocationId` OBLIGATORIO → OPCIONAL: `location_id: LocationId | None = None`.
   - Añadir methods: activate(), deactivate(), archive(), assign_to_location(new_location_id: LocationId | None) → emite ResourceAssignedToLocation.
4. **events.py** (NUEVO resources/events.py): ResourceTypeCreated, ResourceCreated, ResourceActivated, ResourceDeactivated, ResourceArchived, ResourceAssignedToLocation → frozen DomainEvent subclases.
5. **ports.py** resources → Añadir `IResourceTypeRepository` Protocol. Actualizar `IResourceRepository.get(...)` signature para aceptar tenant_id + business_id + resource_id (más amplio). Añadir `list_by_business`, `list_active`. Mantener `list_by_location` existente.
6. **resources/__init__.py** → actualizar exports.

### Test Requirements
**ResourceType (nueva entidad configurable):**
- **rule TR3.1:** create OK (name, tenant_id, business_id obligatorios).
- **rule TR3.2:** name vacío → InvariantViolationError.
- **rule TR3.3:** activate → deactivate → archive OK; archived no vuelve activate.

**Resource actualizado:**
- **rule TR3.4:** create OK con resource_type_id (no más enum), location_id opcional puede ser None.
- **rule TR3.5:** activate/deactivate/archive OK.
- **rule TR3.6:** assign_to_location a location_id nuevo → emite ResourceAssignedToLocation.
- **rule TR3.7:** Tenants distintos: is_isolated (implícito en validación).

---

## Task 4: Tests de dominio completos + Fixes en el camino
**Status:** pending
**Priority:** high
**Parent AC:** AC-24..AC-27 (cobertura)

### Descripción
Crear archivos de tests unitarios de dominio:
- `tests/unit/test_domain_catalog_offering.py`
- `tests/unit/test_domain_catalog_category.py`
- `tests/unit/test_domain_resources_resource_type.py`
- `tests/unit/test_domain_resources_resource.py`

+ test para OfferingResourceRequirement (puede ir en test_domain_catalog_offering_category junto a offering).

### Test Requirements
**Rubric TR4.1 Calidad tests dominio (escala 0-2):**
- 2 = todos los rule tests de TR2 y TR3 passing; 0 skips; coverage mental > 80% de reglas dominio.
- 1 = casi todos passing; algunos skips justificados.
- 0 = fallos > 2.
**Threshold ≥ 2.**

---

## Task 5: Application — Catalog use cases (commands/queries/handlers)
**Status:** pending
**Priority:** high
**Parent AC:** AC-8, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-17, AC-42

### Descripción
Crear `src/universal_business/application/catalog/` con 4 archivos:
1. **__init__.py** → exports públicos.
2. **commands.py** frozen dataclass (Command base subclass):
   - CreateOffering (con idempotency_key: IdempotencyKey | None = None)
   - ActivateOffering / DeactivateOffering / ArchiveOffering
   - ChangeOfferingPrice (new_price: Money)
   - CreateCatalogCategory (con idempotency_key opcional)
3. **queries.py** (Query base subclass frozen):
   - GetOffering (tenant_id, business_id, offering_id)
   - ListOfferingsByBusiness
   - ListOfferingsByLocation
   - ListActiveOfferings
   - ListCategoriesByBusiness
4. **handlers.py** classes (UseCaseHandler Protocol via structural typing):
   - **CreateOfferingHandler:** constructor injection repositories (IOfferingRepository + ICatalogCategoryRepository), UnitOfWork. Usa `execute_use_case` helper. Idempotency path: reserve/create/complete; exc → release → raise.
   - **ActivateOfferingHandler, DeactivateOfferingHandler, ArchiveOfferingHandler, ChangeOfferingPriceHandler:** mutación sobre offering existente, validar tenant/business match, no idempotencia.
   - **CreateCatalogCategoryHandler** idempotency path.
   - **Query handlers:** GetOfferingQueryHandler, ListOfferingsByBusinessQueryHandler, etc. (no UoW; lectura directa).

Fake repositories + FakeUoW + FakeEventPublisher + FakeDispatcher se implementan localmente en tests.

### Test Requirements
- **rule TR5.1:** CreateOffering happy path + events post-commit only.
- **rule TR5.2:** CreateOffering idempotency conflict path (segunda reserva → devuelve cached o error).
- **rule TR5.3:** CreateOffering exc → rollback + release idempotency + 0 events publicados.
- **rule TR5.4:** cross-tenant mutation denied → handler lanza ApplicationError.
- **rule TR5.5:** ActivateOffering / Deactivate / Archive handlers lifecycle OK.
- **rule TR5.6:** ChangeOfferingPrice handler OK + PriceChanged event.
- **rule TR5.7:** CreateCatalogCategory handler + parent!=self validate.
- **rule TR5.8:** Queries ListOfferingsByBusiness/ListActive devuelven resultados filtrados.

---

## Task 6: Application — Resources use cases (commands/queries/handlers)
**Status:** pending
**Priority:** high
**Parent AC:** AC-8, AC-9, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-17, AC-42

### Descripción
Crear `src/universal_business/application/resources/`:
1. **__init__.py**
2. **commands.py**:
   - CreateResourceType (idempotency_key opcional)
   - CreateResource (idempotency_key opcional)
   - ActivateResource / DeactivateResource / ArchiveResource
   - AssignResourceToLocation
3. **queries.py**:
   - GetResource
   - ListResourcesByBusiness
   - ListResourcesByLocation
   - ListActiveResources
   - ListResourceTypesByBusiness
4. **handlers.py**: CreateResourceTypeHandler (idempotency path), CreateResourceHandler (idempotency path), lifecycle handlers, AssignResourceToLocationHandler, Query handlers.

### Test Requirements
- **rule TR6.1:** CreateResourceType + CreateResource happy paths + events post-commit.
- **rule TR6.2:** idempotency reserve/complete/release en failure.
- **rule TR6.3:** AssignResourceToLocation emite AssignedToLocation event + cross-tenant denied.
- **rule TR6.4:** lifecycle handlers OK (archived no vuelve).
- **rule TR6.5:** queries return filtered data.
- **rule TR6.6:** cross-tenant mutation denied en resource/resource_type.

---

## Task 7: Architecture tests nuevos AT-18..AT-22 + no breaks AT-1..AT-17
**Status:** pending
**Priority:** high
**Parent AC:** todos, NFR-6

### Descripción
Añadir a `tests/architecture/test_architecture_boundaries.py` tests AT-18..AT-22 si no duplican AT-7/AT-8 existentes:
- AT-18: catalog/resources domain NO import application.
- AT-19: application/catalog y application/resources NO import infrastructure/api/verticals.
- AT-20: no sector-specific identifiers en nuevos módulos (reutiliza AT-6 existente? si AT-6 ya hace grep en TODO `src/` no duplicar; skip justificado).
- AT-21: repos nuevos (IOffering, ICategory, IResourceType, IResource) son Protocol (no clases concretas).
- AT-22: todos los métodos list/get de repos nuevos tienen `tenant_id` explícito en signature.

### Test Requirements
- **rule TR7.1:** pytest test_architecture_boundaries.py AT-1..AT-22 0 failures.
- **rule TR7.2:** skips de ATs redundantes justificados inline.

---

## Task 8: Documentación Gate 0.3
**Status:** pending
**Priority:** medium
**Parent AC:** AC-30

### Descripción
1. `docs/DEVELOPMENT_STATUS.md` → bump a versión `0.3.0`. Marcar Gate 0.3 = "CERRADO". Añadir milestone 0.3 items. Listar puertas de calidad.
2. `docs/ARCHITECTURE.md` → Añadir sección `### Catalog & Resources (Gate 0.3)`: Offering, CatalogCategory, OfferingResourceRequirement, ResourceType (entidad configurable), Resource actualizado.
3. Crear `docs/plan_entrega_0.3_catalog_resources.md` con items §33 checklist y especificación.
4. Actualizar `src/universal_business/__init__.py` versión paquete a `0.3.0`.
5. Opcional ADR-010 "Offering as universal catalog abstraction" si se considera necesario documentar decisión arquitectónica nueva vs ADR-003 existente. Si ADR-003 ya lo cubre, skip y comentar en ARCHITECTURE.md.

### Test Requirements
- **rule TR8.1:** `universal_business.__version__` (si existe) == "0.3.0" (o equivalente).
- **rule TR8.2:** Documentos no vacíos y no contienen nombres sectoriales prohibidos AT-6.

---

## Task 9: Quality Gate final §32 + commit exacto + push origin
**Status:** pending
**Priority:** high
**Parent AC:** Todos, §32, §35

### Descripción
Ejecutar en ORDEN EXACTO §32:
1. `python -m pytest -q`
2. `ruff check .`
3. `ruff format --check .`
4. `mypy src`
5. `git diff --check`
6. `git status`
7. Grep manual prohibidos: `grep -RniE "fastapi|starlette|sqlalchemy|alembic|redis|celery|kafka|pika|openai|anthropic|stripe|twilio|firebase" src/universal_business` (solo docstrings permitidas).
8. Scope audit: `git diff master...HEAD --name-only` concentrado en `domain/catalog/`, `domain/resources/`, `application/catalog/`, `application/resources/`, `tests/`, `docs/`.

Si TODO pasa:
```
git add .
git commit -m "feat(catalog): establish Gate 0.3 catalog and resources"
git push origin feat/fase-2-catalog-resources
```

Finalmente: Informe §36 20 campos.

### Test Requirements
- **rule TR9.1:** TODAS las puertas 1..8 exit code 0 o vacío según corresponda.
- **rule TR9.2:** Commit mensaje exacto + push successful.
- **rule TR9.3:** 0 cambios en infrastructure/api/verticals concretos (salvo skeleton __init__ no tocados).
