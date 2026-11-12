# F3.11 — Transiciones privadas de pedidos: laboratorio HTTP + SQLite

**Estado:** implementación opcional para desarrollo y pruebas. No activada en la
composición local estándar ni en React; no apta para producción.

## Composición explícita

El adaptador `SqliteStaffOrderTransitions` exige `connect`, un diccionario
de ámbitos publicados `PublicCatalogScope` y una política
`OrderTransitionPolicy` explícita y conservadora. El servidor HTTP requiere
las cuatro dependencias antes de exponer funcionalidad operativa:

- `staff_session_reader` de servidor confiable, sin fallback Bearer;
- `staff_published_scopes` correspondiente a los ámbitos publicados;
- `staff_mutation_csrf` con secreto seguro y orígenes HTTPS exactos;
- `staff_order_transitions` con política y conexión SQLite de laboratorio.

La ruta instalada
`POST /api/v1/staff/businesses/{business_slug}/locations/{location_slug}/orders/{order_id}/transitions`
devuelve 503 cuando falta una dependencia. El único campo de cuerpo permitido
es `{"action":"validate"}` o una de las acciones enumeradas por
`OrderManagementAction`. Requiere `Idempotency-Key` (8 a 128 caracteres
alfanuméricos, guion o guion bajo), `Origin` y `X-CSRF-Token`.

## Orden de verificación

1. Composición completa y sesión opaca válida/revocable. Sin cookies, 401.
2. Ámbito publicado y permiso `manage_orders` del sujeto autenticado.
   `read_orders` no concede escritura.
3. Verificación CSRF de Origin exacto, sesión, negocio, ubicación y acción.
4. Resolución de pedido con IDs internos del servidor y comprobación de tenant,
   negocio y ubicación. Un pedido ajeno devuelve 404.
5. Comprobación de transición e invocación de
   `SqliteOrderExecution.change_status` con política explícita, UoW,
   idempotencia y outbox existentes. El handler vuelve a proteger el ámbito.
6. Respuesta 200 con ID opaco y estado efectivamente almacenado, o replay
   validado con la misma clave y digest. Una acción repetida con nueva clave
   no equivale a un replay y devuelve 409.

El código HTTP nunca acepta IDs internos, roles, permisos, total, estado final
arbitrario ni identidad declarados por un cliente. La política se suministra
por servidor. La aceptación de `validate` con permiso válido se demuestra
solo sobre pedidos sintéticos.

## Cobertura y límites

Las pruebas ejercitan FastAPI + SQLite reales: transición válida, replay sin
duplicación de outbox ni idempotencia; 401, 403, 404 y 422 con ausencia de
cambios; 409 por nueva clave para transición repetida y por política de
negocio denegada con rollback. Se comprueban contadores de `idempotency` y
`transactional_outbox` además del estado de los pedidos.

**No disponible para uso real:** no hay login/IdP, emisión HTTP segura de
cookies ni prueba CSRF, secret manager, sesiones compartidas, autorización
operacional auditada de forma duradera, política comercial real,
controles de infraestructura, revisión de concurrencia multiproceso, ni
interfaz de escritura en React. El publisher exterior del laboratorio es
no-op; el outbox SQLite almacena el evento sin despachar nada al exterior.
La aplicación debe permanecer limitada a datos sintéticos y SQLite solo
desarrollo/pruebas. No se realizan despliegues.
