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

## Propuesta de revisión — 28-10-2026 (PR en borrador)

Este apartado está propuesto para el hardening de la rama de trabajo; no modifica
el estado de aprobación del gate ni afirma que exista un adaptador durable.

- El puerto conserva `tenant_id` explícito. La aplicación deriva una clave de
  almacenamiento versionada a partir de `business_id`, nombre cualificado de la
  operación y clave aportada; el tenant permanece en la frontera del puerto.
- La huella v1 de la solicitud incluye el tipo de comando y sus campos, excepto
  la clave; usa representación determinista y rechaza valores no soportados.
  Igual scope, clave y huella permite replay; una huella distinta falla cerrada.
- La actualización cambia el formato previo de clave y huella: los registros
  existentes **no se migran automáticamente**. Antes de desplegar con datos
  durables hay que acordar migración o caducidad, evitando repetir efectos.
- La reserva, el registro del resultado y el commit del dominio no son atómicos
  en el contrato actual. Un fallo de complete después del commit conserva la
  reserva y exige reconciliación; bloqueo duradero y recuperación transaccional
  requieren diseño y pruebas de integración posteriores.
- El requisito de idempotencia de pedidos y reservas sigue siendo parte de 0.4;
  todavía no se han implementado sus handlers. Los hooks y las carreras deben
  revisarse antes de aprobar este hardening.
