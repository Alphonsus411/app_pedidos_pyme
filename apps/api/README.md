# API local del prototipo

Adaptador HTTP independiente del núcleo. Expone GET /health y, cuando el
entorno compone explícitamente los adaptadores SQLite, catálogo público,
creación de borradores y lectura de pedidos de personal. El módulo no abre
SQLite por sí mismo.

Instalación local desde la raíz del repositorio:

    python -m pip install -e ".[api,dev]"
    uvicorn apps.api.app.main:app --reload

La creación pública solo deja pedidos en estado `draft`: no los valida, confirma,
cobra ni envía notificaciones. Requiere `Idempotency-Key`, resuelve el ámbito en
el servidor y recalcula el importe desde las ofertas activas.

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
