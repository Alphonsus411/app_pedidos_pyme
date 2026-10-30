# Contrato v1 y separación de aplicaciones

Estado: contrato inicial de F1 y avances acotados de F2. Existe una API local
con rutas públicas y una primera lectura privada; no existe un sistema de
identidad listo para producción, paneles ni integración del frontend.

## Decisión de organización

Durante el prototipo se mantiene un único repositorio para el núcleo Python y su documentación. Los consumidores se ejecutan y evolucionan como proyectos independientes:

- Núcleo: dominio, aplicación y adaptadores de infraestructura; no conoce HTTP, React ni marcas de clientes.
- Servicio API futuro: paquete o aplicación separada que depende del núcleo solo mediante casos de uso y puertos públicos.
- Panel de negocio, panel de plataforma y sitios: repositorios o paquetes independientes; consumen HTTP y nunca importan `universal_business`, repositorios SQLite ni tablas.
- Fripollo: aplicación React independiente. Su catálogo ficticio sirve de fixture o semilla de demostración, no de regla del dominio.

La transición a repositorios separados se decidirá cuando la API local tenga contratos y pruebas reproducibles. No se publica ningún paquete ni se fija una semántica de versionado externo en este incremento.

## Dependencias permitidas

| Componente | Puede depender de | No puede depender de |
|---|---|---|
| Dominio | librería estándar y tipos de dominio | HTTP, SQLite, React, marcas |
| Aplicación | dominio y puertos | frameworks web, componentes de cliente |
| Infraestructura | aplicación y dominio | interfaces cliente |
| API futura | casos de uso, puertos e infraestructura compuesta | código de sitios o paneles |
| Sitio/panel | contrato HTTP publicado | núcleo Python, SQLite, secretos |

La validación de estas fronteras se incorporará con pruebas de arquitectura cuando exista el paquete API. La ocultación de elementos en una interfaz nunca sustituye la autorización del servidor.

## Borrador del contrato HTTP

Prefijo: `/api/v1`. JSON UTF-8. Las rutas materializadas se documentan junto a
sus limitaciones; el resto del contrato sigue siendo evolutivo.

### Lectura pública de catálogo

- `GET /public/businesses/{business_slug}/locations/{location_slug}/catalog`
- Solo devuelve artículos visibles y la información pública necesaria para mostrar la carta.
- No acepta `tenant_id` ni `business_id` como ámbito de confianza: el servidor los resuelve desde slugs y configuración validada.
- Paginación futura: `limit` y cursor opaco `cursor`; no exponer offsets como contrato de estabilidad.

### Creación de pedido de cliente

- `POST /public/businesses/{business_slug}/locations/{location_slug}/orders`
- Requiere `Idempotency-Key` por solicitud; la misma clave con cuerpo distinto devuelve conflicto.
- El cliente solo remite artículos y cantidades. El servidor resuelve disponibilidad, nombres, moneda, precio e importes desde su catálogo.
- Nunca se aceptan total, descuento, impuesto, estado ni identificadores de tenant procedentes del navegador.
- La respuesta describe el estado real persistido; no comunica pago, envío o notificación si no existe esa integración.

### Operaciones privadas de personal

- `GET /staff/businesses/{business_slug}/locations/{location_slug}/orders`: lectura inicial de pedidos. Requiere Bearer, el permiso `read_orders` y asociación explícita al negocio y ubicación solicitados.
- `GET /staff/businesses/{business_slug}/locations/{location_slug}/orders/{order_id}`: detalle de un pedido solo si pertenece al ámbito ya autorizado. Un identificador malformado o ajeno responde como no encontrado y no concede ni revela acceso entre negocios.
- El prototipo compone un autenticador de tokens estáticos fuera de la aplicación; no emite, almacena, rota ni revoca tokens. Sirve para validar la frontera de autorización y no es una solución de identidad de producción.
- Toda ruta `/staff/...` posterior requiere identidad autenticada, rol y asociación vigente a negocio y ubicación.
- `/platform/... `: requiere rol de plataforma explícito. No hereda acceso a datos de todos los negocios por ser administrador.
- Las rutas privadas derivan el ámbito de identidad y verifican cada recurso en el servidor. Un identificador de URL, cabecera o cuerpo no concede privilegios.

## Formato común de errores

Todas las rutas futuras usarán:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Descripción segura para el cliente",
    "request_id": "uuid-o-correlación"
  }
}
```

Códigos iniciales reservados: `validation_error`, `authentication_required`, `forbidden`, `not_found`, `conflict`, `idempotency_conflict`, `rate_limited` e `internal_error`. Se incorpora además `service_unavailable` para composición local ausente. Los detalles de infraestructura, SQL, secretos y trazas no se devuelven al cliente.

Las rutas actuales ya devuelven este sobre de error y una cabecera `X-Request-ID`. Si el cliente aporta una cabecera con UUID válido se conserva; si no, el servidor genera una nueva. Esto no equivale aún a auditoría persistente, trazas distribuidas ni política de retención.

## Datos, importes y compatibilidad

- Los importes se serializarán como cadenas decimales y código ISO de moneda; no se usa `float`.
- La versión mayor vive en la URL. Cambios incompatibles requieren una nueva versión o una transición documentada.
- Los identificadores expuestos son opacos. Los consumidores no dependen de nombres de tablas ni de claves internas.
- CORS, límites de solicitud, credenciales, retención y observabilidad se fijarán por entorno al implementar F2.

## Criterios realizados y siguientes de F2

1. Revisar este borrador frente a los casos de uso existentes.
2. Elegir la forma concreta del servicio API sin mover todavía el frontend.
3. Escribir pruebas de contrato y de acceso cruzado entre dos negocios antes de declarar una ruta privada.
4. Mantener SQLite real para las pruebas de transacción del prototipo, sin afirmar garantías de producción.
5. Sustituir el autenticador estático por una identidad gestionada, con secretos por entorno, expiración, revocación, auditoría y pruebas negativas adicionales antes de uso real.
