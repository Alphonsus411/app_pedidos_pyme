# F3.15 — Reconciliación tras respuesta perdida (laboratorio)

**Estado:** pruebas de contrato de reconciliación sobre la implementación existente; sin nuevo endpoint ni automatismo de reintento. Únicamente datos sintéticos y SQLite de desarrollo/pruebas.

## Problema

Después de confirmar una transición y sus registros de idempotencia/outbox, el cliente puede no recibir el HTTP 200. Un timeout o pérdida de respuesta **no prueba** que la transacción haya fallado. Repetir la acción con una clave nueva puede producir un conflicto o intentar una nueva operación no deseada.

## Procedimiento permitido

1. Conservar la acción, ámbito, ID de pedido y la **misma Idempotency-Key** de la petición original.
2. Recuperar sesión válida y permisos de servidor; para consultar el estado actual se necesita explícitamente `read_orders`, distinto de `manage_orders`.
3. Solicitar `GET /api/v1/staff/businesses/{business_slug}/locations/{location_slug}/orders/{order_id}` solo en ámbito autorizado. El estado actual permite inspección, pero **no acredita por sí solo cuál solicitud causó el cambio**.
4. Repetir el **mismo POST**, con el mismo ámbito, acción, pedido y clave idempotente; regenerar el token CSRF válido para la sesión actual si corresponde. El contrato de idempotencia debe recuperar el resultado confirmado sin duplicar outbox ni registros de idempotencia.
5. Si el servidor no responde o se recibe 503, mantener resultado **incierto** y reintentar únicamente con límites/backoff tras recuperar servicio. 409 con otra clave no equivale a un replay exitoso.

## Evidencia automatizada

`tests/api/test_staff_order_transitions.py` descarta deliberadamente el objeto de respuesta HTTP **después** de la ejecución del handler y del commit real, reconstruye un cliente independiente con sesión opaca y verifica GET autorizado y replay con la misma clave, sin duplicar outbox ni idempotencia. Comprueba también que una clave distinta recibe 409, que un pedido de otro negocio se oculta (404), que `manage_orders` no concede lectura privada (403) y que la revocación invalida tanto GET como POST (401).

**Limitación importante:** descartar la respuesta de un `TestClient` es una simulación determinista de incertidumbre del cliente, **no** una desconexión TCP, interrupción del proceso ni fallo real de commit. No se garantizan resultados frente a caídas del almacenamiento, confirmaciones ambiguas o múltiples procesos.

SQLite permanece exclusivamente en laboratorio, sin frontends activados ni IAM productivo. Revisar la dependencia en cadena F3.12 → F3.13 → F3.14 antes de integrar F3.15. Ejecutar pytest, Ruff y mypy en CI Python 3.11 y 3.12.
