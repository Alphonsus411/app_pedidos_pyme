# F4.10 — Reintento de paginación pública tras error transitorio

Incremento de regresión, sin cambio de comportamiento productivo: Playwright simula un GET público de primera página, un 503 transitorio al solicitar el cursor y un segundo GET con el mismo cursor que devuelve la página final. Comprueba conservación de artículos y foco tras error, botón reactivado, reintento explícito mediante teclado, desaparición de la alerta tras éxito, deduplicación, foco final, dos intentos con el mismo cursor y ausencia de Authorization, almacenamiento local o rutas privadas.

No se implementan reintentos automáticos ni se alteran contratos HTTP, persistencia, dominio o identidad. SQLite solo desarrollo/pruebas. Requiere CI Python 3.11/3.12 y frontend completa antes de fusionar; sin despliegues.
