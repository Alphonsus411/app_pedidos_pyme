# F4.09 — Robustez de la paginación pública

El catálogo conserva artículos ya cargados y descarta duplicados por `id`, incluso si una respuesta contiene IDs repetidos. El estado accesible anuncia solo los artículos nuevos efectivamente incorporados, o indica que no se han encontrado artículos nuevos. Si el servidor devuelve el mismo cursor solicitado, el cliente detiene la paginación para evitar un bucle inmediato. El comportamiento de errores transitorios existente mantiene los artículos y permite reintentar con el botón.

Playwright cubre páginas duplicadas, vacías y cursor repetido con respuestas sintéticas. Limitaciones: no se implementa detección de ciclos de cursor de longitud mayor que uno; los IDs deben respetar el contrato de la API. Sin cambios de endpoints, dominio, persistencia, autenticación ni operaciones privadas. SQLite solo desarrollo/pruebas. PR pendiente de CI Python 3.11/3.12 y frontend completa antes de squash merge.
