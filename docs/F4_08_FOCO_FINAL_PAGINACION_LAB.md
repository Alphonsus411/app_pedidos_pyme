# F4.08 — Foco accesible al agotar páginas públicas

Al recibir una respuesta sin `next_cursor` tras pulsar «Cargar más artículos», el botón desaparece. El panel traslada entonces el foco a la región de estado de paginación (`role=status`, `tabIndex=-1`) una vez React ha actualizado el árbol. El foco no se mueve en la carga inicial ni cuando quedan páginas; tampoco se fuerza ante errores. La región sigue anunciando el resultado mediante `aria-live=polite`.

Playwright verifica con teclado la última página, el cierre del botón, el foco en el estado y que las solicitudes son GET públicos sin Authorization. No constituye auditoría WCAG completa. Sin cambios de API, dominio, persistencia, autenticación, operaciones privadas ni despliegues; SQLite solo desarrollo/pruebas. Exigir CI Python 3.11/3.12 y frontend antes de merge.
