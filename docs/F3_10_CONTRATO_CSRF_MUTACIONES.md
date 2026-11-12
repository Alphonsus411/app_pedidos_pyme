# F3.10 — Contrato CSRF para futuras mutaciones de pedidos staff

**Estado: guard de laboratorio y pruebas, sin endpoint de escritura, login ni activación en el panel.**

## Componente

`apps/api/app/staff_csrf.py` define `StaffMutationCsrf` y `CsrfRejected`.
El guard requiere un secreto de servidor de al menos 32 bytes y una lista exacta
de orígenes HTTPS permitidos. El servidor puede emitir una prueba HMAC-SHA256
ligada a la sesión opaca, negocio, ubicación y acción.

En la verificación, la prueba recibida por un encabezado CSRF futuro debe
coincidir en tiempo constante y la cabecera `Origin` debe existir y
corresponder exactamente a un origen permitido. No se acepta un `Referer`
como sustituto ni se acepta una lista de orígenes amplia por comodín.

## Orden obligatorio para cualquier endpoint futuro

1. El servidor valida la cookie mediante el lector de sesiones confiable,
   comprobando expiración y revocación, sin fallback a Bearer estático.
2. Resuelve el ámbito publicado y comprueba `manage_orders` del principal.
3. Verifica `Origin` y prueba CSRF usando exclusivamente el identificador
   de sesión verificado del servidor; nunca confía en sesión o grants enviados
   como campos del JSON o cabeceras arbitrarias.
4. Relee el pedido dentro del mismo tenant, negocio y ubicación; comprueba
   estado y política transaccional de transición.
5. Solo entonces ejecuta el comando con UoW, outbox e idempotencia. Deben
   revalidarse permisos antes de devolver un replay.

La emisión de la prueba debe diseñarse y protegerse como parte del flujo real
de sesión. Este incremento **no incorpora ese endpoint**, no instala cookies,
no configura secretos, no implementa un proveedor de identidad y no modifica
pedidos. El guard por sí solo no autentica ni impide que un atacante con sesión
comprometida actúe.

## Evidencias y limitaciones

Pruebas de `Origin` ausente o erróneo, HTTP, tokens falsificados, contexto
de otra sesión, otro negocio, ubicación o acción, orígenes ambiguos, secret
insuficiente y parámetros inválidos. CI Python 3.11 y 3.12 con pytest, Ruff
y mypy satisfactoria en rama; revisar nuevamente tras la documentación.

No se afirma seguridad productiva: quedan pendientes IdP, cookies emitidas
por un servicio confiable, gestión y rotación de secreto, sesiones distribuidas,
auditoría duradera, límites de infraestructura, pruebas de navegador y
pruebas de escritura transaccional. SQLite solo desarrollo y pruebas.
