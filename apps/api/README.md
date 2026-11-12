# API local del prototipo

Adaptador HTTP independiente del núcleo. Expone GET /health y, cuando el
entorno compone explícitamente los adaptadores SQLite, catálogo público,
creación de borradores y lectura de pedidos de personal. El módulo no abre
SQLite por sí mismo.

Instalación local desde la raíz del repositorio:

    python -m pip install -e ".[api,dev]"
    uvicorn apps.api.app.main:app --reload

Para componer las rutas de negocio durante desarrollo, use un JSON externo no
versionado y ejecute:

    UNIVERSAL_BUSINESS_API_LOCAL_CONFIG=/ruta/local-api.json \
      uvicorn apps.api.app.local_entry:app --reload

El JSON debe contener `sqlite_path`, una lista de `scopes`,
`staff_credentials` y `cors_origins`. Las credenciales son tokens estáticos
exclusivos de desarrollo: no incluya un archivo con secretos en Git ni lo use
en producción.

La creación pública solo deja pedidos en estado `draft`: no los valida, confirma,
cobra ni envía notificaciones. Requiere `Idempotency-Key`, resuelve el ámbito en
el servidor y recalcula el importe desde las ofertas activas.

El catálogo público acepta `limit` entre 1 y 100 y un cursor opaco `cursor`; la
respuesta devuelve `next_cursor` o `null`. El cursor no concede acceso ni
contiene ámbitos internos de negocio. En este prototipo SQLite el adaptador aún
carga el resultado del catálogo antes de recortarlo; no es paginación eficiente
para catálogos grandes.

La lectura bajo `/api/v1/staff/...` exige `Authorization: Bearer` y comprueba un
permiso de lectura limitado al negocio y ubicación solicitados. Durante el
prototipo, el autenticador recibe tokens estáticos por composición explícita: no
emite tokens, no almacena credenciales y no es apto para producción. Siguen
pendientes un proveedor de identidad, gestión segura de secretos, renovación y
revocación de credenciales, auditoría, límites y configuración por entorno.

Las rutas privadas disponibles son el listado de pedidos de una ubicación y el
detalle de un pedido dentro de ese mismo ámbito. Un identificador de pedido no
amplía permisos: si no pertenece al negocio y ubicación autorizados, responde
como no encontrado. Son operaciones de lectura; no validan, confirman ni
modifican pedidos.

Los errores HTTP del adaptador usan `{ "error": { "code", "message",
"request_id" } }` y devuelven el mismo UUID en `X-Request-ID`. Una cabecera
`X-Request-ID` con UUID válido se conserva; cualquier otro valor se reemplaza.
El identificador ayuda a correlacionar la solicitud, pero todavía no existe
registro de auditoría ni observabilidad externa.

CORS solo se activa si la composición recibe una lista cerrada de orígenes
HTTP(S). No admite `*`, rutas ni orígenes con credenciales, y permite los
encabezados necesarios para los contratos actuales. El valor depende del
entorno consumidor; no hay ningún origen de Fripollo codificado en la API.

## Creación atómica de borradores multilínea (F2.1; PR #90)

La composición local en la rama de PR #90 crea el pedido y todas sus líneas en una sola UoW SQLite. Un fallo previo al commit revierte pedido, líneas, idempotencia y outbox; un replay idéntico devuelve el borrador persistido siempre que conserve íntegramente las líneas esperadas. Una solicitud modificada con la misma clave se rechaza. No se reparan automáticamente borradores parciales históricos.

Esta capacidad sigue siendo de desarrollo y pruebas; no confirma pedidos, no cobra ni envía mensajes, y no implica preparación para producción. Las rutas privadas siguen usando identidad técnica estática de laboratorio.

## Aislamiento de identificadores públicos (F2.2; PR #90)

Los nuevos ID de pedidos se derivan de tenant, negocio, ubicación y clave de idempotencia; reutilizar una misma clave en negocios distintos del mismo tenant no colisiona. Si existe un borrador histórico con el identificador v1 en el mismo ámbito se conserva para replay, previa comprobación de contenido y scope. No se reparan borradores históricos incompletos ni se migra la base. Esta medida no sustituye identidad ni rate limiting.

## Límites de entrada de pedidos públicos (F2.3.1)

El endpoint POST público valida antes de persistir: máximo 50 líneas, cada offering_id con 36 caracteres, quantity positiva y <=1000 con máximo cuatro decimales y doce dígitos y una cabecera Idempotency-Key de 1–128 caracteres ASCII dentro de un patrón restringido. Los errores de validación HTTP devuelven 422 y no crean pedidos.

Son límites del contrato HTTP del prototipo, no una implementación de rate limiting, autenticación de clientes o filtrado de tamaño bruto del cuerpo a nivel de proxy. Los controles de despliegue siguen pendientes; SQLite es exclusivamente de desarrollo y pruebas.

## Política de cuota local optativa (F2.3.2)

`create_app(public_order_limiter=LocalPublicOrderRateLimiter(limit=10, window_seconds=60))`
permite inyectar desde el proceso de aplicación una ventana deslizante de
solicitudes para POST público de borradores. El valor 10/60 es solo un ejemplo,
no un umbral recomendado para producción. El componente devuelve 429 con
`Retry-After` y conserva el contrato de error/correlación. Se identifica al
cliente mediante `request.client.host` y la ruta pública, nunca por cabeceras
`X-Forwarded-For` no verificadas. Los rechazos se producen antes del cuerpo y
la escritura, y también cuentan las solicitudes fallidas que alcanzan la ruta.

**No se activa en `create_app()` ni en `create_local_app()` por defecto.**
Se puede inyectar explícitamente en tests y en una composición HTTP propia.
Es una protección **por proceso**: no comparte contadores entre réplicas,
no garantiza identidad real del cliente detrás de proxies, ni sustituye el
rate limiting de gateway/CDN, la limitación de bytes de cuerpo, la autorización
o las medidas contra abuso distribuidas. Para producción son obligatorias
políticas centralizadas y un diseño independiente de observabilidad.

## Límite bruto del cuerpo de pedidos públicos (F2.3.3)

El adaptador admite un middleware ASGI opcional mediante
`create_app(public_order_max_body_bytes=32 * 1024)` (ejemplo de activación).
Se aplica solo al POST de creación pública de pedidos. Comprueba la longitud
declarada y los bytes reales recibidos por fragmentos, sin acumular más del
límite configurado. El componente admite valores de 1 byte a 1 MiB y usa
32 KiB por defecto cuando se instancia directamente. Una solicitud excesiva
recibe HTTP 413 con código `payload_too_large` y correlación por
`X-Request-ID`. Si no se configura, no cambia el comportamiento actual.

No sustituye el límite bruto de un reverse proxy/CDN ni resuelve timeouts,
clientes lentos, cargas de otras rutas o mitigación distribuida. No crea
pedidos durante el rechazo. SQLite permanece exclusivamente en desarrollo y
pruebas; tampoco se ha incorporado autenticación ni despliegue productivo.

## Contrato inyectable de identidad para personal (F2.4)

La factoría HTTP `create_app(staff_authenticator=...)` acepta ahora un
`StaffAuthenticator` estructural: su operación `authenticate(authorization)`
devuelve un `StaffPrincipal` validado o lanza `AuthenticationRequired`.
`StaticBearerAuthenticator` sigue disponible únicamente para desarrollo y
pruebas, sin cambios en la composición local ni en los permisos existentes.
El adaptador SQLite continúa comprobando cada `StaffGrant` por negocio,
ubicación y rol, tanto en listado como en detalle de pedidos.

**Esto no es una integración de identidad de producción.** Quedan pendientes
validación contra un IdP confiable, expiración/rotación/revocación, gestión de
secretos, sesiones, auditoría y revisión de permisos. Los clientes no deben
aportar sus propios grants. Ninguna credencial se versiona.

## Integridad de ámbitos y permisos en la composición local (F2.5)

La carga del JSON local rechaza antes de levantar la aplicación cualquier
`StaffGrant` que se refiera a un `business_slug/location_slug` no publicado.
Asimismo, un `business_slug` no puede asociarse a distintos pares de
`tenant_id/business_id`, ni una ubicación interna puede publicarse bajo
dos rutas distintas. Sí se permiten varias ubicaciones de un mismo negocio
cuando sus identificadores internos son diferentes.

Las comprobaciones son solo de **integridad de la configuración local** y
complementan la autorización por grant que ya ejerce el servidor. No verifican
la identidad real de trabajadores, ni reemplazan IAM, auditoría, revocación,
controles de secretos o políticas de producción. SQLite sigue restringido a
pruebas y desarrollo.

## Puerto opcional de auditoría staff (F2.6)

La factoría de la API admite `create_app(staff_audit_sink=...)` para inyectar
un `StaffAuditSink` que reciba eventos `StaffAccessAuditEvent` de las lecturas
privadas de pedidos (lista y detalle). El evento contiene `request_id`,
`subject` cuando pudo autenticarse, `business_slug`, `location_slug`,
`action` y `status_code`. No contiene `Authorization`, tokens ni
identificadores de pedidos. En las rutas ejecutadas se registran resultados
200, 401, 403, 404, 503 y fallos inesperados con estado 500.

**Alcance del prototipo:** la emisión es optativa, sin almacenamiento duradero
incluido y de mejor esfuerzo: si falla el sink no se altera la respuesta HTTP.
Los errores de validación 422 antes de entrar en el controlador no generan
este evento. Tampoco se registra tráfico público u otras rutas privadas.
No es una auditoría regulatoria ni adecuada para producción sin un sumidero
seguro, persistencia, disponibilidad, controles de acceso, retención y
política explícita ante fallos. SQLite sigue usándose solo en desarrollo/tests.

## Descubrimiento optativo de sesión staff (F3.2, solo contrato)

`GET /api/v1/staff/session` devuelve `{subject, scopes:[{business_slug, location_slug, roles}]}`
únicamente si la composición HTTP inyecta un `StaffSessionReader` confiable y
un registro `staff_published_scopes` obtenido del servidor. Cada ámbito
devuelto es la **intersección** de permisos del sujeto autenticado y ámbitos
publicados. Se deduplican grants y se normaliza el orden. Los ámbitos no
publicados y los permisos no concedidos no se exponen.

Sin proveedor o registro devuelve 503; sin sesión válida, 401. Una respuesta
válida lleva `Cache-Control: no-store`. Esta ruta **no concede permisos**
ni evita la autorización propia de cada operación privada, no inicia sesión,
no guarda cookies, no emite credenciales ni usa tokens estáticos.

**No está conectada en `create_local_app` ni activada en la UI**. La integración
real exige proveedor de identidad, gestión de sesiones y cookies con políticas
seguras, protección CSRF cuando se habiliten mutaciones, revocación, auditoría
y pruebas entre negocios. SQLite solo desarrollo y tests; no publicar el panel.
