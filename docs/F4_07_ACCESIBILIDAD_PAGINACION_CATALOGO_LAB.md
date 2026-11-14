# F4.07 — Accesibilidad de la paginación pública (laboratorio)

La región del catálogo deja de tener `aria-live` sobre todo su contenido, evitando anuncios repetidos de listas extensas. Una región `role=status`, `aria-live=polite` y `aria-atomic=true` anuncia la solicitud de la siguiente página y la cantidad de artículos recibidos en la respuesta. Los errores conservan `role=alert`. La interacción con botón nativo conserva el foco cuando el botón sigue disponible; Playwright lo comprueba mediante teclado y respuestas sintéticas.

Límites: el recuento anunciado corresponde a los elementos recibidos, no necesariamente a nuevos elementos únicos tras deduplicación. Si se agota la paginación, el botón se desmonta y no se garantiza aún recuperación explícita del foco: pendiente de una mejora posterior. No es certificación WCAG. Sin cambios en API, dominio, SQLite, identidad, pagos, operaciones privadas o despliegues. CI Python y frontend completa obligatoria antes de merge.
