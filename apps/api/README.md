# API local del prototipo

Adaptador HTTP independiente del núcleo. Expone GET /health y, cuando el
entorno compone explícitamente los adaptadores SQLite, catálogo público y
creación de borradores de pedido. El módulo no abre SQLite por sí mismo ni
autentica usuarios.

Instalación local desde la raíz del repositorio:

    python -m pip install -e ".[api,dev]"
    uvicorn apps.api.app.main:app --reload

La creación pública solo deja pedidos en estado `draft`: no los valida, confirma,
cobra ni envía notificaciones. Requiere `Idempotency-Key`, resuelve el ámbito en
el servidor y recalcula el importe desde las ofertas activas. La composición,
identidad, autorización, límites y configuración segura por entorno siguen
pendientes.
