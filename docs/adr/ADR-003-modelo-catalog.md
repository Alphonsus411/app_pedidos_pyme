# ADR-003 — Modelo CatalogItem / Product / Service

## Estado
**Aceptado.** Definido en Entrega 0.1.

## Contexto
El core debe representar artículos vendibles en **cualquier vertical**:
productos físicos (pollo, zapatos), servicios (corte de pelo, consulta),
combos (menu infantil), digitales (e-book, suscripción online). ¿Cómo modelar
esto sin duplicación y sin nombres sectoriales?

## Alternativas consideradas
| # | Modelo |
|---|---|
| A | `Product` y `Service` como entidades separadas con tablas distintas. |
| B | Un solo `CatalogItem` con `type ∈ {PRODUCT, SERVICE, BUNDLE, DIGITAL, OTHER}` más `Variant` + `ModifierGroup`. |
| C | Una tabla base por cada tipo con JOINs (TPT). |

## Decisión
**Opción B — `CatalogItem` polimórfico por discriminador.**

Detalles:
- `CatalogItem.type ∈ {PRODUCT, SERVICE, BUNDLE, DIGITAL, OTHER}`.
- Variantes (SKU, precio) como `Variant` asociada.
- Modificadores opcionales vía `ModifierGroup` / `ModifierOption`.
- **Regla de nombres prohibidos** en el core: NO pueden existir nombres como
  `PiezaDePollo`, `ComboPicaPollo`, `MesaRestaurante`, `Peluquero`, etc.
  Los tests arquitectónicos AT-6 detectan ocurrencias textuales.

## Consecuencias
- ✅ Un solo modelo sirve para pica-pollo, peluquería, clínica, tienda online.
- ✅ Nombres de vertical se guardan en `verticals/<sector>/seeds` como datos.
- ⚠️ Riesgo de sobre-abstracción → mitigado: `BusinessSettings` + extensiones
  específicas de vertical cubren comportamientos raros sin tocar el core.
