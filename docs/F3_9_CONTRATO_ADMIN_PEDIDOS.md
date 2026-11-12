# F3.9 — Contrato previo a administración privada de pedidos

**Estado: contrato y regresiones, SIN endpoints de escritura.** No apto para producción.

## Contratos HTTP propuestos, todavía no implementados

Ruta futura: `POST /api/v1/staff/businesses/{business_slug}/locations/{location_slug}/orders/{order_id}/transitions`.

Solicitud futura (no publicada):

```json
{"action": "validate"}
```

La cabecera `Idempotency-Key` será obligatoria para mutaciones. No se aceptarán
`tenant_id`, `business_id`, `status` arbitrario, `roles` ni identidad enviados
desde el navegador. Las acciones admitidas en el contrato son `validate`,
`confirm`, `return_to_draft`, `cancel`, `prepare`, `mark_ready`,
`dispatch` y `complete`.

## Autorización por operación

- El servidor autentica una **sesión confiable** antes de consultar recursos.
- Comprueba que negocio y ubicación figuren en el registro publicado.
- Exige permiso nuevo `manage_orders` para ese negocio y esa ubicación.
  `read_orders` **no equivale** a `manage_orders`; y viceversa.
- Identifica el pedido real dentro del mismo tenant/business/location sin
  aceptar identificadores internos aportados como fuente de autoridad.
- Verifica el estado y la matriz de transiciones del dominio. La prevalidación
  de F3.9 no sustituye las políticas y verificaciones transaccionales del caso
  de uso: confirmar requiere líneas y total coherente.
- Revalida identidad y permiso antes de cualquier respuesta de idempotencia.
  La mutación se ejecutará usando `SqliteOrderExecution.change_status` solo
  en laboratorio, con UoW, eventos, outbox e idempotencia existentes.

## Matriz de estados existente en el dominio

| Estado previo | Destinos legales (sujetos a políticas) |
| --- | --- |
| draft | validated, cancelled |
| validated | draft, confirmed, cancelled |
| confirmed | preparing, completed, cancelled |
| preparing | ready, cancelled |
| ready | delivering, completed, cancelled |
| delivering | completed, cancelled |
| completed | Ninguno |
| cancelled | Ninguno |

No son acciones disponibles en React. Una transición repetida no es
automáticamente aceptada; el contrato de idempotencia debe diferenciar un
replay de una transición nueva.

## Respuestas a verificar antes de publicar el endpoint

| Código | Significado previsto |
| --- | --- |
| 200 | Acción efectuada o replay idempotente verificable |
| 401 | Sesión ausente, caducada o revocada, sin fallback Bearer |
| 403 | Falta `manage_orders` para el ámbito publicado |
| 404 | Ámbito no publicado o pedido inexistente/ajeno |
| 409 | Transición inválida, conflicto de versión, política o idempotencia |
| 422 | Acción, cabeceras o petición malformadas |
| 503 | Dependencias de sesión/persistencia no configuradas |

Todas las respuestas de error mantienen el contrato existente de
`error.code` y `X-Request-ID`. En la implementación futura la mutación por
cookie exigirá defensa CSRF, protección de sesiones, límites de peticiones y
auditoría duradera; ninguna de estas garantías se presume en F3.9.

## Entrega de este incremento

`StaffRole.MANAGE_ORDERS` y
`authorize_order_transition(...)` son una frontera preparatoria **sin
persistencia ni endpoint nuevo**. Las pruebas cubren privilegio de lectura
insuficiente, acceso cruzado entre negocios/ubicaciones, ámbito ausente y
transiciones legales/ilegales con la matriz original. No se modifica el núcleo,
ni React, ni la composición local; SQLite continúa solo para desarrollo/test.

Siguiente incremento, separado y sujeto a revisión: implementar la ruta
servidor con autenticación de sesión real de laboratorio, comprobación del
pedido antes de escribir, política explícita, idempotencia, protección CSRF y
pruebas de rollback/aislamiento. No activarlo en React hasta demostrar todos
esos controles.
