# F4.06 — Accesibilidad del detalle público

El botón de expansión expone `aria-expanded` y `aria-controls` apuntando al `id` de la región del artículo cuando está abierta. El identificador de región deriva del índice de la lista renderizada, no de una cadena arbitraria de API. El detalle conserva su nombre accesible y el botón nativo permite activación por teclado.

La prueba Playwright con datos sintéticos comprueba foco, activación con Enter, correspondencia entre `aria-controls` y región, cierre, bloqueo de controles privados y solo peticiones GET públicas. La región se monta únicamente mientras está abierta; `aria-controls` puede referenciar un elemento ausente cuando está cerrada. Esto es un incremento limitado de accesibilidad, no una certificación WCAG.

Sin cambios en dominio, API, persistencia, identidad, pedidos o despliegue. SQLite exclusivamente para desarrollo y pruebas. Exigir CI Python 3.11/3.12 y frontend completo antes de fusionar.
