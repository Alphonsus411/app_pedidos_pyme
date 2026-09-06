# ADR-008 — Semántica transaccional en Application Layer (UnitOfWork + eventos)

## Estado
**Aceptado.** Definido en Gate 0.2 (Foundation / Application Layer).

## Contexto
El patrón Transactional Outbox (ADR-004) requiere una frontera transaccional
explícita en Application Layer antes de publicar eventos a sistemas externos.
En Gate 0.1 el dominio solo recolectaba `DomainEvent`s; no existía
`UnitOfWork` ni un flujo canónico de ejecución de caso de uso. Sin una
convención explícita es muy fácil:
1. publicar eventos **antes** de persistir/commit (consistencia rota);
2. hacer commit implícito en `__exit__` (doble commit accidental);
3. no hacer rollback ante excepciones de dominio o infraestructura.

## Alternativas consideradas
| # | Estrategia | Semántica |
|---|---|---|
| A | `UnitOfWork.commit()` implícito al salir del context manager si no hay excepción. | Código cliente más corto. |
| B | Commit **explícito** obligatorio; `__exit__` sin commit → `rollback()`. | Fallo rápido; no doble commit; commit es decisión consciente. |
| C | `begin()` + `commit()` + `rollback()` manual (sin context manager). | Verboso pero 100% explícito. |

Para eventos post-commit:
| # | Estrategia |
|---|---|
| 1 | Publicar eventos **dentro** del UnitOfWork antes de commit. | Muy peligroso (evento enviado pero rollback después). |
| 2 | Commit OK → zona post-commit: dispatcher interno síncrono + EventPublisher externo (ADR-009). | Consistencia fuerte; el dominio queda persistido antes de notificar. |
| 3 | Commit OK → solo escribir en tabla Outbox dentro del UoW. | Requiere infraestructura (Gate 0.5), en 0.2 es prematuro. |

## Decisión
**Opción B + Opción 2.**

Convención canónica de caso de uso:

```
1. Entrar en UnitOfWork (context manager __enter__).
2. Ejecutar lógica de dominio (handler.handle()).
3. LLAMADA EXPLÍCITA: unit_of_work.commit().
4. Salir del context manager (__exit__):
   - Si NO hubo excepción y sí commit(): nada, transacción cerrada OK.
   - Si NO hubo excepción pero SIN commit() → rollback().
   - Si hubo excepción → rollback() y propagar excepción.
5. ZONA POST-COMMIT (fuera del context manager, solo si commit OK):
   a. Recolectar eventos (list(events)).
   b. Despachar DomainEventDispatcher interno (handlers síncronos app-level).
   c. Publicar vía EventPublisher port (para futuros Outbox/Kafka/webhooks).
6. Devolver resultado del handler.
```

Reglas inviolables:
- **NUNCA se publica/dispacha eventos antes de commit.**
- **NUNCA commit implícito en `__exit__`** (commit es decisión de código cliente).
- **Si commit falla → 0 eventos publicados/dispachados.**
- **Si handler falla → rollback + 0 eventos.**
- **Si post-commit falla (dispatcher/publisher): el resultado ya fue committeado,
  no se hace rollback.** El código cliente es responsable de reintentar o
  manejar (los eventos ya están confirmados lógicamente).

Para idempotencia (Gate 0.2):
- `IdempotencyStore.reserve()` debe ocurrir **dentro** del UnitOfWork antes del
  commit. Si reserve() devuelve False → lanzar IdempotencyConflictError
  (rollback).

## Consecuencias
- ✅ Consistencia fuerte entre estado de dominio y publicación de eventos.
- ✅ Error rápido si alguien olvida `commit()` (rollback automático, no hay
  "commit accidental").
- ✅ El helper `execute_use_case` encapsula la semántica canónica (una única
  fuente de verdad en lugar de repetir el flujo en cada caso de uso futuro).
- ⚠️ Fallos en post-commit NO deshacen el dominio. El diseñador de futuros
  casos de uso debe saber que dispatch/publish pueden fallar
  independientemente.
- ⚠️ **`EventPublisher` NO es atómico DB+message.** Publicar post-commit
  significa que los datos ya están confirmados; si el publisher falla el
  dominio no se deshace. El patrón Transactional Outbox mitiga esto pero:
  (1) en Gate 0.2 **no está implementado**; (2) cuando exista (Gate 0.5+) se
  materializará como un **contrato separado**
  (p. ej. ``TransactionalOutboxWriter`` invocado pre-commit dentro del UoW),
  NO compartiendo interfaz con ``EventPublisher`` (que seguirá siendo
  post-commit).
- ⚠️ Handlers síncronos post-commit NO deben modificar agregados (fuera de UoW).
  Si un handler necesita modificar estado → debe lanzar un comando nuevo o ser
  un caso de uso separado.
- ⚠️ **Idempotency: liberar reservas en fallo.** Si ``reserve()`` tuvo éxito
  pero el handler/UoW falla antes de ``complete()``, es obligatorio llamar a
  ``release()`` para devolver la key a ``FREE``. Gate 0.2 no asume TTL; sin
  ``release()`` la key permanece ``RESERVED`` indefinidamente.
