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
