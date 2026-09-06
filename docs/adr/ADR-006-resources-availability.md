# ADR-006 — Representación de Recursos y Disponibilidad

## Estado
**Aceptado.** Definido en Entrega 0.1 (solo CONTRATOS; implementación del motor → FASE 1).

## Contexto
El roadmap define `Resources` (mesa, profesional, sala, pista, equipo) y
`Availability` (calendarios, capacidad, ventanas, bloqueos, reglas). Se usan
en múltiples verticales: restaurante mesa/horario, peluquería
silla/profesional/turnos, clínica sala/agenda, hotel habitación/estancia.

## Alternativas consideradas
| # | Modelo |
|---|---|
| A | `Resource` genérico + `AvailabilityRule` separado + `Block` de excepciones. |
| B | Todo dentro de `Resource` como 1:1 (disponibilidad mergeada en el propio recurso). |
| C | `Schedule` entidad separada con N:M a Resource. |

## Decisión
**Opción A.**

### Entregado en Entrega 0.1
- **Solo contratos** `IResourceRepository` + `IAvailabilityRepository` (Protocol).
- `Resource` entidad esqueleto: `ResourceType ∈ {TABLE, ROOM, STAFF, EQUIPMENT, SLOT, OTHER}`; `location_id` OBLIGATORIO (físicamente pertenece).
- `AvailabilityRule` esqueleto y `AvailabilityBlock` esqueleto.

### FASE 1 (implementación del motor)
- Motor de disponibilidad: `find_available(resource_id|type, location_id, range) → list[Slot] + capacidad residual`.
- Evalúa reglas + blocks con prioridad y solapes.

## Consecuencias
- ✅ Una Location puede mezclar múltiples Resources (pica: mesas; pelu: sillas + profesionales; clínica: salas/doctores).
- ⚠️ Complejidad alta del motor → mitigado: unit-testable sin infraestructura.
