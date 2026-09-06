# ADR-005 — Modelo de extensiones verticales (Regla de Oro)

## Estado
**Aceptado.** Definido en Entrega 0.1.

## Contexto
El primer cliente del UBC es un negocio de *pica-pollo* (pollo frito). Si
cualquier nombre o regla de ese vertical se filtra dentro de
`universal_business/*`, el core deja de ser universal y no puede reutilizarse
para peluquería, clínica, etc. ¿Cómo extender sin contaminar?

## Alternativas consideradas
| # | Modelo |
|---|---|
| A | Monkeypatching dinámico al importar `verticals/pica_pollo/`. |
| B | Clases abstractas en el core con implementaciones por vertical. |
| C | 3 niveles de extensión: **Configuración → Semillas → Extensiones específicas**. |

## Decisión
**Opción C — Config / Seeds / Extensions.**

Dirección de dependencias estricta:
```
verticals/<sector>/  -->  application/  -->  domain/
```

- **Nada en `domain/` o `application/` conoce** la existencia de
  `verticals/pica_pollo/`. No hay imports "hacia arriba".
- Los nombres sectoriales viven como **datos** en seeds, no como identificadores
  en Python.
- Tests arquitectónicos AT-6 grepean el core buscando tokens prohibidos
  (`picapol`, `restaurante`, `peluqueria`, `clinica`, `barber`, `hotel`, …).

## Consecuencias
- ✅ Añadir un nuevo vertical = añadir carpeta `verticals/<sector>/`.
- ✅ Feature envy / leak hacia el core detectado en CI.
- ⚠️ Los casos de uso realmente sectoriales tienen que vivir en
  `verticals/<sector>/application_services.py` (duplicación mínima).
