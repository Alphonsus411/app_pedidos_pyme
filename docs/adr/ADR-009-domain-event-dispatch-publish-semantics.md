# ADR-009 — Domain Event Dispatching vs Event Publishing (separación de responsabilidades)

## Estado
**Aceptado.** Definido en Gate 0.2 (Foundation / Application Layer).

## Contexto
ADR-004 definió:
1. El dominio NUNCA envía eventos; solo los recolecta (`AggregateRootMixin.add_domain_event`).
2. Transactional Outbox como patrón a futuro.

En Gate 0.2 es necesario desambiguar dos conceptos frecuentemente confundidos:
- **Dispatch interno síncrono:** handlers dentro del mismo proceso, mismos datos
  lógicos del evento, sin serialización, sin red. Usado para: reglas de aplicación
  que deben ejecutarse "inmediatamente después" de un cambio de dominio (ej:
  recalcular un agregado dependiente, escribir un read model en memoria, enviar
  una notificación interna).
- **Publish externo / integración:** envío a otros procesos/sistemas vía Outbox
  / Kafka / Rabbit / webhook / etc. Requiere serialización, idempotencia, reintentos.

Si ambos conceptos comparten el mismo nombre/clase/contrato, la aplicación
acaba mezclando reglas de negocio internas con integración externa.

## Alternativas consideradas
| # | Estrategia |
|---|---|
| A | Un solo `EventBus` que hace todo (dispatch interno + publish externo). |
| B | **Dos puertos separados**: `DomainEventDispatcher` (interno síncrono) + `EventPublisher` (externo / integración). |
| C | Solo `EventPublisher`. Los handlers internos son "subscribers" con un nombre de bus local. |

Para el `DomainEventDispatcher` (interno):
| # | Estrategia de registro |
|---|---|
| 1 | Autodiscovery por reflexión / decorador global. |
| 2 | **Registro explícito** por constructor / método `register(type, handler)`. |
| 3 | Diccionario service locator con imports mágicos. |

Para resolución de handlers herencia MRO:
| # | Estrategia |
|---|---|
| 1 | Solo handlers exactos (`type(event) == EventX`). |
| 2 | **Handlers subtipo + MRO** (un handler de `DomainEvent` genérico recibe TODOS los eventos). |

Para error de handler:
| # | Estrategia |
|---|---|
| 1 | Handler falla → continuar con los siguientes handlers. |
| 2 | **Handler falla → propagar excepción y abortar dispatch.** (Coherencia fuerte para síncrono). |
| 3 | Envolver en `AggregateError`. |

## Decisión
**Opción B + Registro explícito (2) + MRO subtipo (2) + Propagación de excepción (2).**

Definiciones Gate 0.2:

1. **`DomainEventHandler[EventT]` (Protocol):**
   - Contracto de handler síncrono interno.
   - Método único: `handle(event: EventT) -> None`.
   - Se ejecuta en la zona post-commit (ADR-008).

2. **`DomainEventDispatcher` (componente con estado):**
   - Registro explícito: `dispatcher.register(EventType, handler)`.
   - Orden determinista: **orden de registro** para handlers de un mismo tipo.
   - Resolución MRO: `type(event).__mro__` (más específico → más genérico).
     Handlers de `DomainEvent` reciben TODOS los subtipos.
   - `dispatch(event)`: único evento. Valida `isinstance(event, DomainEvent)`.
   - `dispatch_many(events)`: **eager validate** (materializa list → valida que
     TODO elemento sea `DomainEvent` ANTES de invocar a ningún handler → si hay
     un elemento no válido, nada se procesa).
   - **Excepción propagada**: si un handler lanza, el dispatch aborta y la
     excepción sube (no sigue con los siguientes handlers). Quien llama decide
     cómo proceder (en `execute_use_case` la excepción sube; el dominio ya fue
     commitado).

3. **`EventPublisher` (Protocol / port de infraestructura):**
   - Contrato para publicadores externos / integración.
   - `publish(event: DomainEvent) -> None`
   - `publish_many(events: Sequence[DomainEvent]) -> None` (default: iterar `publish`).
   - **Invocación exclusivamente post-commit (ADR-008 paso 5).** NO se usa
     dentro del UnitOfWork.
   - **NO garantiza atomicidad DB + message.** Si falla, el dominio ya está
     committeado y no se deshace.
   - **NO escribe un Outbox físico dentro del UoW.** Si en Gate 0.5+ se adopta
     Transactional Outbox, existirá un port **separado** (p. ej.
     ``TransactionalOutboxWriter``) que se invoque pre-commit dentro del UoW;
     :class:`EventPublisher` seguirá siendo el componente post-commit que
     envía/mueve mensajes al bus externo.
   - NO se implementa en 0.2 (solo es el port). Futuros backends:
     Outbox físico, Kafka, RabbitMQ, webhooks, etc. NINGUNO de estos nombres
     aparece en el core.

4. **Flujo post-commit canónico (ADR-008 paso 5):**
   - Primero `event_dispatcher.dispatch_many(events_list)` (handlers internos síncronos).
   - Después `event_publisher.publish_many(events_list)` (integración externa).

## Consecuencias
- ✅ Separación clara: el dispatcher es un componente lógico de la aplicación
  y su semántica es conocida; el publisher es un port para adaptadores futuros.
- ✅ Registro explícito: magia 0. Fácil de testear, fácil de seguir con
  grep/IDE, sin service locator.
- ✅ MRO subtipo: un auditor genérico (handler de `DomainEvent`) recibe todos
  los eventos sin necesidad de registrar N veces.
- ✅ Dispatch_many eager validate: no se dejan "eventos a medio procesar"
  (consistencia determinista para los handlers síncronos).
- ⚠️ Excepción propagada en handler síncrono: como el commit YA ocurrió
  (post-commit), la excepción NO deshace el dominio. El diseñador del caso de
  uso debe ser consciente (para casos críticos usar handler que no falle o
  envolver en try/except local si corresponde).
- ⚠️ El publisher NO tiene `unit_of_work` en el signature (post-commit), por
  diseño. El futuro adapter de Outbox físico (Gate 0.5) necesitará su propia
  TX / retry.
