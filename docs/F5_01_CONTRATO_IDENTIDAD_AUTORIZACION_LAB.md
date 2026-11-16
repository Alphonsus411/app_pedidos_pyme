# F5.01 — Contrato de identidad y autorización (diseño, no implementación)

## Objetivo y límites
Definir el contrato mínimo para habilitar operaciones privadas **solo después** de implementar autenticación y autorización reales en el servidor. Esta fase es documental: no crea credenciales, sesiones, tokens, rutas privadas operativas ni acceso del panel a datos de personal. SQLite permanece exclusivamente en desarrollo/pruebas; no se despliega.

## Frontera de confianza
- El cliente React consume exclusivamente API HTTP versionada. Nunca consulta base de datos ni considera fiable el negocio, ubicación, rol o identidad que declare el navegador.
- El servidor autentica cada solicitud privada, resuelve la identidad de la sesión, obtiene las pertenencias vigentes a negocio y ubicación y autoriza la acción concreta sobre el recurso.
- La ausencia de identidad, una sesión expirada/revocada, una pertenencia inactiva o un permiso insuficiente producen denegación antes de acceder o modificar recursos.
- La autorización no depende de botones deshabilitados, rutas ocultas ni datos del frontend. Los endpoints públicos siguen siendo de solo lectura y sin credenciales inventadas.

## Modelo conceptual propuesto (sin migraciones)
- `Principal`: identificador opaco, estado activo/bloqueado.
- `Session`: identificador opaco revocable, principal, vencimiento absoluto e inactividad, rotación y trazabilidad; cookies HttpOnly, Secure y SameSite según despliegue y protección CSRF si se usan cookies para mutaciones.
- `Membership`: principal, negocio, ubicación opcional, estado y vigencia; toda asignación se valida en servidor.
- `Permission`: capacidad específica (por ejemplo, `orders:read`, `orders:create`, `reservations:read`) asociada a rol o política; denegación por defecto y mínimo privilegio.
- `AuditEvent`: resultado de autorización y referencia de solicitud, sin registrar secretos ni datos sensibles innecesarios.

## Matriz de aceptación antes de habilitar rutas privadas

| Escenario | Resultado esperado |
| --- | --- |
| Sin sesión | 401, sin filtración de existencia de recursos |
| Sesión caducada o revocada | 401 y ninguna lectura/escritura privada |
| Sesión válida, permiso insuficiente | 403, sin acceso al recurso |
| Negocio o ubicación ajenos | Denegación, sin acceso cruzado entre tenants |
| Pertenencia retirada durante sesión | Denegación inmediata o coherente con política documentada de revocación |
| Rol con permiso mínimo y ámbito correcto | Solo operación autorizada |
| Recurso inexistente o ajeno | Política uniforme de 404/403 que no permita enumeración |
| Mutación concurrente o reintento | Idempotencia y transacción según contrato de pedidos/reservas, nunca asumidas por la sesión |
| Cambio de identidad o privilegios | Rotación/revocación de sesión y auditoría |
| Acceso desde frontend | Solo HTTP API; sin tokens en localStorage y sin claves simuladas |

## Dependencias y puertas de salida
1. Revisar endpoints privados existentes, semántica HTTP y modelos de negocio antes de escribir código.
2. Elegir proveedor y mecanismo de autenticación compatible con la infraestructura autorizada; modelar sesiones y revocación en persistencia real, no en SQLite productivo.
3. Definir política de permisos por operación, ámbito y recurso con tests negativos multiempresa.
4. Implementar middleware/dependencias de autorización en servidor y pruebas de contrato 401/403/404; prohibir accesos por SQL cruzado.
5. Solo después conectar UI privada a sesiones reales, con protección CSRF/CORS y gestión de errores.
6. Validar CI Python 3.11/3.12 y frontend aplicable; revisión de seguridad antes de producción.

## Decisión de esta fase
**Diseño propuesto, no gate cerrado.** No se presume implementación ni autorización para activar endpoints. Próxima tarea: inventario de rutas y modelo de amenazas acotado; después una implementación aislada por incrementos verificables.
