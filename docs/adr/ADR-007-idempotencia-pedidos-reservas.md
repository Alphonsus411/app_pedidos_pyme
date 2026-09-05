# ADR-007 — Idempotencia para Pedidos y Reservas

## Estado
**Aceptado.** Definido en Entrega 0.1 (contrato; implementación de la entidad → FASE 1).

## Contexto
Un reintento HTTP, un webhook reenviado o un usuario que pulsa dos veces
"confirmar reserva" NO deben duplicar un pedido o una reserva. El PDF exige
"operaciones externas sensibles con idempotencia".

## Alternativas consideradas
| # | Modelo |
|---|---|
| A | Cabecera HTTP `Idempotency-Key` + tabla por endpoint. |
| B | `IdempotencyKey` como entidad de dominio: `(scope, key, tenant_id, business_id)` ÚNICO. |
| C | Llaves por customer.external_ref + fecha (débil). |

## Decisión
**Opción B.**

### Contrato para FASE 1
- `IdempotencyScope ∈ {ORDER_CREATE, RESERVATION_CREATE, ORDER_CONFIRM, RESERVATION_CONFIRM, ...}`.
- Entidad `IdempotencyKey`: `idempotency_id`, `scope`, `key`, `aggregate_type`,
  `aggregate_id` (nullable), `created_at`, `locked_until` (TTL).
- Flujo en application service:
  1. Si la llave `(scope, key, tenant, business)` existe → **retornar el aggregate ya creado** (NO副作用重复).
  2. Si no existe → crear aggregate + registrar la llave **dentro de la misma transacción**.
- Exclusividad a nivel `(tenant_id, business_id)`; no global (multi-tenant).

### Entrega 0.1
- ❌ NO se implementa la entidad.
- ✅ Se define la decisión y se reserva el espacio (el ADR es el contrato).

## Consecuencias
- ✅ Reintentos seguros por diseño.
- ✅ Integrable con webhooks y cualquier canal (WhatsApp, API, cliente móvil).
- ⚠️ Toda API de mutación requiere llave → mitigado: hash determinista como
  valor por defecto en canales que no la proveen; TTL por scope.
