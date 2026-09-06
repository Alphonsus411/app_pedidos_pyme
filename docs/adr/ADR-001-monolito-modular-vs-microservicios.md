# ADR-001 — Monolito modular frente a microservicios

## Estado
**Aceptado.** Definido en Entrega 0.1.

## Contexto
El roadmap (`hoja_ruta_universal_business_core.pdf`) recomienda un único
despliegue inicial. El proyecto es pre-mvp: aún no hay verticales en
producción, ni límites de agregados validados empíricamente, ni métricas de
escalado por módulo. Se debe escoger entre microservicios desde el día 1, un
monolito clásico sin límites, o un **monolito modular con límites estrictos**.

## Alternativas consideradas
| Alternativa | Ventajas | Inconvenientes |
|---|---|---|
| **A) Microservicios desde cero** | Escalado independiente, desacoplamiento forzado. | 12+ servicios, API Gateway, service mesh, coste operativo brutal; límites aún no validados → monolito distribuido muy probable. |
| **B) Modular monolith con strict boundaries + architecture tests** | Un solo despliegue. Límites por paquete + tests que protegen la dirección de imports. Fácil extraer un servicio más tarde cuando los límites estén probados. | Riesgo de "big ball of mud" si no se aplican los tests arquitectónicos — mitigado por AT-1..AT-8. |
| **C) Single-tier sin límites** | Velocidad corta. | No sobrevive a la segunda vertical. No es viable. |

## Decisión
**Opción B — Modular monolith con strict boundaries.**

Condiciones de migración a microservicios (todas deben darse):
1. Dos o más verticales en producción con carga real.
2. Los límites módulo-a-módulo se mantienen estables ≥ 2 releases.
3. Hay una necesidad operacional demostrada (independencia de escalado o releases).

## Consecuencias
- ✅ Despliegue único; observabilidad simple; una sola DB inicialmente.
- ✅ Los límites se definen por paquete (`domain/<mod>/`, `application/<mod>/`,
  `infrastructure/<mod>/`) y se validan automáticamente en CI (AT-1..AT-8).
- ⚠️ Riesgo de acoplamiento accidental → mitigado: los imports cruzados
  inter-módulo en el dominio deben pasar por **puertos** (Protocol); no por
  imports directos a internals de otro agregado.
- ⚠️ Extraer un servicio en el futuro requiere disciplina → planificado como
  ejercicio rutinario de cada release ("¿Se podría extraer X como servicio hoy?").
