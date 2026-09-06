# Development Status

> Documento de continuidad técnica. Última actualización: 06-sep-2026 (Gate 0.1 Final Audit).
> Propósito: retomar el proyecto en semanas o meses sin depender de memoria de conversación.

---

## Project

| Campo | Valor |
|---|---|
| Nombre | **Universal Business Core** (paquete `universal_business`) |
| Repositorio GitHub | `app_pedidos_pyme` |
| Versión actual (semver) | `0.1.0` (Entrega 0.1 — Architectural Baseline) |
| Stack | Python ≥3.11, pytest ≥8, ruff ≥0.4, mypy ≥1.10 |
| Runtime dependencies | **0** (vacío; core puro sin frameworks) |

---

## Current Git State

| Campo | Valor |
|---|---|
| Rama actual de trabajo | `feat/architectural-baseline` |
| Working tree | **limpio** |
| Sincronización remota | `up to date with origin/feat/architectural-baseline` |
| `master` | **intacta** en `25fc345` |

### Commits relevantes (top-down)

```
* 3143ef1 (HEAD, origin/feat/architectural-baseline)  docs: update DEVELOPMENT_STATUS HEAD SHA after final audit commit
* 57e7001  docs: finalize Gate 0.1 audit; pin dev tooling ranges for reproducibility
* ddadd7b  docs: add project README and development status
*   889fb21  merge: integrate remote baseline history before RC1
|\
| * 8ba78e1  Creamos e incluimos documento de auditoria .txt
* | 7a705fc  fix: harden Gate 0.1 architectural baseline
|/
* 93d3e95  feat: implement Universal Business Core architectural baseline
* 256cd8f  chore: remove temporary planning output
* adbdc75  docs: refine architectural baseline plan
* 3bb3738  feat: add architectural baseline and project structure
* ebff09f  feat(docs): add PDF generator for architectural baseline plan
* 25fc345 (origin/master, origin/HEAD, master)  chore: initialize Universal Business Core repository
```

### Nota sobre `auditoria_gate_0_1.txt`

El archivo **NO forma parte del árbol actual** (no aparece en `git ls-files`).
Únicamente permanece en el historial Git dentro del commit `8ba78e1`.
El merge commit `889fb21` lo eliminó explícitamente del árbol final.

---

## Current Architecture

Monolito modular DDD con capas segregadas. Dirección única de dependencias:

```
    API / Channels (vacío 0.1)
          │
    Application (vacío 0.1)
          │
    Domain ──── Ports (Protocols, NO implementación)
          │
    Infrastructure (vacío 0.1)

    └── verticals/  ←── dependen HACIA DENTRO, nunca al revés (vacío 0.1)
```

- **Domain-centric / Ports & Adapters.**
- **Multi-tenant lógico** `Tenant → Business → Location`.
- **Vertical extensions desacopladas** (ADR-005).
- **Domain agnostic**: nada en `src/universal_business/domain/` conoce nombres de verticales concretas (ej. pica-pollo).

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

## Technical Validation

Ejecutados por última vez: 05-sep-2026 (Python 3.11, Windows sandbox).

| Verificación | Comando exacto | Resultado |
|---|---|---|
| Tests unit + arquitectura + imports | `python -m pytest` | **418 passed** |
| Ruff lint | `ruff check .` | **All checks passed** |
| Ruff formatter | `ruff format --check .` | **60 files already formatted** |
| Mypy strict GLOBAL | `mypy src` | **Success: no issues found in 47 source files** |
| Import core sin externos | `python -c "import universal_business; print(universal_business.__version__)"` | **`0.1.0`** OK |
| Working tree | `git status` | **clean** |
| Repo sync | `git branch -vv` | **up to date with origin/feat/architectural-baseline** |

---

## Current Repository Boundaries

```
src/universal_business/
├── __init__.py               ← version = "0.1.0"
├── api/                      ← SOLO __init__.py (vacío). NO FastAPI.
├── application/              ← SOLO __init__.py (vacío). NO use cases.
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
[test_architecture_boundaries.py](file:///C:/Users/Adolfo/PycharmProjects/app_pedidos_pyme/tests/architecture/test_architecture_boundaries.py) (AT-1..AT-9).

---

## Explicitly Not Implemented

TODOS los items siguientes **NO existen y no deben introducirse hasta FASE ≥1 con plan
explícito aprobado**:

### Frameworks / Infraestructura
- ❌ FastAPI / Starlette
- ❌ SQLAlchemy
- ❌ PostgreSQL / drivers DB
- ❌ Alembic (migrations)
- ❌ Redis
- ❌ Kafka / RabbitMQ / brokers de mensajes
- ❌ Celery / RQ / tareas asíncronas distribuídas

### Servicios externos / integraciones
- ❌ WhatsApp / SMS
- ❌ Firebase / FCM
- ❌ LLM / AI integrations
- ❌ Payment gateways (Stripe, Mercado Pago, Culqi…)
- ❌ Delivery providers (Uber Eats, Rappi, Glovo…)
- ❌ Frontend: React, React Native, Vue, Svelte…

### Contenido de verticales
- ❌ Vertical pica-pollo (cualquier código, regla, nombre)
- ❌ Cualquier otro vertical implementado

### Lógica funcional
- ❌ Persistencia real (solo Ports Protocol)
- ❌ Use cases / CQRS / UnitOfWork completos
- ❌ Pricing avanzado / SKU / variantes de catálogo
- ❌ Stock real
- ❌ Motor de disponibilidad / scheduling
- ❌ Ciclo completo de pedidos / reservas (líneas, impuestos, descuentos)
- ❌ Fulfillment operacional
- ❌ Outbox físico / dispatcher eventos

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
- Rama `feat/architectural-baseline` publicada en origin.
- **NO existe trabajo de FASE 1 en curso.**
- **NO hay trabajo pendiente sin commit en esta rama.**
- **Master intacta, sin merge.**

### Roadmap por etapas (estado factual actual)

| Etapa | Alcance | Estado |
|---|---|---|
| **0.1 Architectural Baseline** | Dominio + VOs + Entidades + Ports + Tests AT-1..AT-9 + CI + Docs | ✅ COMPLETE |
| **0.1-RC1 Hardening** | Tenancy explícita, Currency sin whitelist, metadata inmutable, mypy strict global | ✅ COMPLETE |
| **0.2 Foundation / Core** | Use cases skeleton, UnitOfWork, aplicación, vertical skeleton, comando/queries base | ⚪ **NOT STARTED** — NO debe empezarse sin plan formal. |
| **0.3 Catalog & Resources** | SKU, pricing, stock, capacity, variantes | ⚪ NOT STARTED |
| **0.4 Orders & Reservations** | Ciclo completo, líneas, impuestos | ⚪ NOT STARTED |
| **0.5 API & Persistence** | FastAPI, SQLAlchemy, PostgreSQL, outbox físico | ⚪ NOT STARTED |
| **0.6 First Vertical** | Ej. pica-pollo u otro TBD | ⚪ NOT STARTED |
| **0.7+ Channels & automation** | WhatsApp, webhooks, delivery providers | ⚪ NOT STARTED |

Cualquier continuación debe arrancar con el paso "Siguiente paso recomendado"
siguiente, NO continuando directamente en esta rama con código FASE 1.

---

## Next Recommended Actions

Orden estricto recomendado al retomar:

1. **Confirmar que el árbol sigue válido:** ejecutar el *Resume Checklist* (abajo).
2. **Crear PR formal** en GitHub: `feat/architectural-baseline → master`.
3. **Revisar CI del PR**; el workflow `.github/workflows/ci.yml` corre automáticamente en PR a master.
4. **Mergear SOLO si CI está 100% verde** (418 tests, ruff, mypy).
5. Después del merge a `master`:
   - Actualizar localmente `master` al HEAD mergeado (`git checkout master && git pull`).
   - **Crear una NUEVA rama** para la siguiente entrega (nunca seguir escribiendo directamente
     sobre `feat/architectural-baseline`). Nombre sugerido: `feat/fase-1-foundation` o similar.
6. **Definir formalmente el scope de la siguiente fase** antes de abrir IDE: escribir
   plan, criterios de aceptación y Gate correspondiente. NO decidir el contenido de FASE 1
   sobre la marcha.
7. Conservar como inamovibles los 13 + 21 criterios de G0.1 y G0.1-RC1 (nadie vuelve a
   introducir Float para dinero, ni whitelist cerrada para Currency, ni repos tenant-scoped
   sin `tenant_id` explícito).

---

## Resume Checklist

Al retomar, ejecuta ESTOS comandos y verifica que todo coincide. Si algo cambió,
no continúes sin entender por qué.

### 1. Estado Git

```bash
git status
# Esperado: On branch feat/architectural-baseline
#          nothing to commit, working tree clean

git branch -vv
# Esperado: * feat/architectural-baseline  3143ef1  [origin/feat/architectural-baseline]  docs: update DEVELOPMENT_STATUS HEAD SHA after final audit commit

git log --oneline --decorate --graph --all -n 15
# Esperado: 3143ef1 → 57e7001 → ddadd7b → 889fb21 → (7a705fc, 8ba78e1) → 93d3e95 → ... → master=25fc345
```

### 2. Validación técnica

```bash
python -m pytest
# Esperado: 418 passed

ruff check .
# Esperado: All checks passed!

ruff format --check .
# Esperado: 60 files already formatted

mypy src
# Esperado: Success: no issues found in 47 source files
```

### 3. Import + versión

```bash
PYTHONPATH=src python -c "import universal_business; print(universal_business.__version__)"
# Esperado: 0.1.0
```

Si todo lo anterior coincide, puedes proceder a crear PR a master. Si no coinciden los
números, algo cambió: revisa `git diff` antes de continuar.
