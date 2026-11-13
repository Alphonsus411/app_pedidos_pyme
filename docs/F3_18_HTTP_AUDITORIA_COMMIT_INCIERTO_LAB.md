# F3.18 — Contrato HTTP y auditoría de commit incierto (laboratorio)

**Estado:** pruebas HTTP parametrizadas y corrección mínima del contrato de errores. Base: F3.17 en la misma rama (PR #112). Solo SQLite sintético de desarrollo/pruebas; sin despliegue.

## Hallazgo y corrección

La prueba detectó que una excepción inesperada devolvía el JSON HTTP 500 sanitizado con `error.request_id`, pero **sin cabecera `X-Request-ID`**, porque el middleware no alcanzaba la asignación de cabecera cuando su procesamiento interno lanzaba una excepción.

Se modificó solamente `apps/api/app/error_contract.py`: el constructor común `_error_response` incluye explícitamente `X-Request-ID` en todas las respuestas de error que genera. Se conserva el `request_id` ya calculado y se respetan las otras cabeceras, por ejemplo `Retry-After`. No se modificó el núcleo, esquema ni políticas de autorización.

## Evidencia

Las pruebas F3.18 componen un `create_app` de laboratorio con sesión de servidor, CSRF, ámbito publicado, sumidero `StaffAuditSink` en memoria y adaptador SQLite con excepción inyectada una sola vez **antes** o **después** de `sqlite3.Connection.commit()`:

- Ambos casos devuelven **500**, `error.code=internal_error`, `error.message=Internal server error`, y una cabecera `X-Request-ID`, sin detalles internos, clave idempotente ni identificador de pedido.
- El evento de auditoría contiene `action=transition_order`, código **500**, `subject` autenticado y el **mismo** `request_id` que la respuesta, sin credenciales ni datos de pedido.
- Se compara la persistencia mediante nuevas conexiones: antes del commit, pedido `draft` y sin nuevas filas; después del commit, pedido `validated`, una clave idempotente y un evento outbox.
- Una solicitud HTTP repetida con **misma clave/acción/ámbito** obtiene 200 en ambos casos sin duplicados; una clave nueva resulta en 409. La auditoría refleja la secuencia 500, 200, 200, 409.

## Garantías y límites

La prueba inyecta una **excepción sintética de Python**, no una caída de red, apagón o fallo de disco. El código 500 no prueba ni éxito ni fracaso del commit. La correlación HTTP permite investigar, pero la auditoría **no** es durable ni prueba el resultado de la transacción. Los clientes deben mantener la misma clave idempotente y reconciliar conservadoramente, como describen F3.15–F3.17.

Pendientes: pruebas de fallos físicos y multiproceso, identidad real, auditoría durable, despliegue e integración del panel. SQLite exclusivamente en laboratorio. Validación mediante pytest, Ruff y mypy en Python 3.11 y 3.12.
