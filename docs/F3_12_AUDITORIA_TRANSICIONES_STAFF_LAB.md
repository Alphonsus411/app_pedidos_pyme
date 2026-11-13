# F3.12 — Auditoría mínima de transiciones privadas (laboratorio)

**Estado:** incremento optativo, exclusivo de desarrollo y pruebas con datos sintéticos. No habilita la interfaz privada ni concede preparación para producción.

## Alcance

El endpoint `POST /api/v1/staff/businesses/{business_slug}/locations/{location_slug}/orders/{order_id}/transitions` reutiliza el puerto inyectable `StaffAuditSink`, ya empleado por las lecturas privadas. Para cada petición que alcanza el handler registra un `StaffAccessAuditEvent` con:

- `request_id` emitido por el middleware de correlación.
- `subject` obtenido exclusivamente de la sesión de servidor si esta se autentica; de lo contrario, `None`.
- `business_slug` y `location_slug` solicitados (no equivalen a autorización).
- `action="transition_order"`, nombre de operación genérico.
- `status_code` HTTP observado, incluidos 200, 401, 403, 404, 409 y 503.

No se incluyen ID de pedido, token de sesión, cookie, prueba CSRF, clave de idempotencia, valores monetarios ni cuerpo de la solicitud. Un replay idempotente registra una nueva solicitud HTTP pero **no** crea otra mutación ni otro evento outbox. El registro no distingue éxito nuevo de replay, evitando inferir una semántica que el puerto actual no representa.

## Semántica y límites

El registro se realiza en `finally` para cubrir denegaciones y errores del handler; una excepción del sink se ignora de forma *best-effort* sin cambiar el resultado HTTP. Las validaciones de FastAPI/Pydantic que rechazan una solicitud **antes de entrar en el handler** (por ejemplo 422) no están cubiertas por este puerto; tampoco se registran garantías de durabilidad, orden, entrega o inmutabilidad.

El sumidero no se activa por defecto. No existe almacenamiento auditable durable, cola, retención, política de acceso a registros ni observabilidad productiva. El proyecto sigue utilizando SQLite únicamente para desarrollo/pruebas y mantiene pendientes identidad real, IdP, cookies emitidas por backend, políticas comerciales definitivas, concurrencia multiproceso y despliegue.

## Validación requerida

`tests/api/test_staff_order_transitions.py` cubre respuestas 401/403/404/200/409, replay, correlación de petición, minimización de datos y fallo aislado del sink. Ejecutar localmente:

```bash
python -m pytest -q tests/api/test_staff_order_transitions.py
ruff check apps/api/app/main.py tests/api/test_staff_order_transitions.py
ruff format --check apps/api/app/main.py tests/api/test_staff_order_transitions.py
mypy src
```

La integración no debe fusionarse sin CI satisfactoria y revisión de las restricciones de seguridad. Sin cambios en dominio, aplicaciones de cliente, workflows ni datos de producción.
