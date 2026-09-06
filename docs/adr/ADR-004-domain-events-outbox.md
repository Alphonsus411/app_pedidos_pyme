# ADR-004 — Eventos de dominio y patrón Outbox

## Estado
**Aceptado.** Definido en Entrega 0.1. Implementación OUTBOX físico = FASE 2/3.

## Contexto
Muchos casos de uso futuros dependen de efectos secundarios después de
persistir un agregado: enviar WhatsApp, imprimir ticket en cocina, guardar
registro de auditoría, sincronizar con un ERP. La forma clásica (llamar a
notificadores **dentro** de los métodos del agregado) acopla el dominio a
infraestructura.

## Alternativas consideradas
| # | Estrategia |
|---|---|
| A | Llamadas directas desde aggregate methods a services (emailer, repo, etc.). |
| B | Aggregate recolecta `DomainEvent`s; la capa de aplicación los persiste junto  al agregado en la MISMA transacción (patrón **Transactional Outbox**) y luego los despacha. |
| C | Publicar directamente en un bus transaccional (BD especializada / Kafka TX). |

## Decisión
**Opción B** con una implementación **faseada**:

### Fase actual (Entrega 0.1 / RC1 Hardening)
- ✅ `DomainEvent` base mínimo (ver `domain/shared/events.py`).
- ✅ `AggregateRootMixin` (recolección en memoria, sin envío).
- ✅ **(RC1) Inmutabilidad semántica de metadata:** `DomainEvent` es frozen
  dataclass, y su `metadata` se convierte mediante copia defensiva a
  `types.MappingProxyType`. Nada del código posterior al `__init__` puede
  mutar los metadatos (`event.metadata["x"]=v`, `update`, `del` fallan), y
  un dict original pasado al constructor que se mute después **NO** afecta
  al evento.
- ❌ **Sin tabla outbox, sin dispatcher, sin bus.**

### Fase 2 / 3 (fuera de 0.1)
- Añadir tabla `domain_outbox` en infrastructure.
- Implementar `Application service` que persista agregado + eventos en una TX.
- Dispatcher que lee el outbox y publica (reintentos / idempotencia).

Regla inviolable: **el dominio NUNCA envía eventos; solo los recolecta.**

## Consecuencias
- ✅ Consistencia transaccional (cuando se implemente la tabla outbox).
- ✅ El dominio sigue limpio (sin dependencias de infra).
- ⚠️ Complejidad añadida en FASE 2/3 (orden, batching, dead-letter queue).
