# ADR-007 — Idempotencia de operaciones

## Estado

La decisión de aislar las operaciones por tenant, negocio, tipo y clave fue
aceptada en la base 0.1. **La revisión técnica siguiente está propuesta en el
PR #4 y aún no ha sido aprobada ni integrada.** No implica que pedidos o
reservas tengan ya handlers idempotentes.

## Contexto y decisión histórica

Un reintento de cliente o una entrega repetida no debe duplicar efectos. Se
eligió identificar una operación mediante `(tenant, business, operación, clave)`
en vez de deducirla de un cliente y una fecha. La decisión histórica proponía
registrar clave y agregado en una misma transacción; el núcleo actual no dispone
de adaptador durable que implemente esa garantía.

## Propuesta de contrato para el hardening

- El cliente proporciona una clave de idempotencia para las operaciones que
  lo requieran. La política exacta por operación se definirá en 0.4. Los cuatro
  creates existentes de catálogo y recursos aún permiten omitirla; con clave,
  el store debe estar disponible.
- El port exige `tenant_id` explícito y recibe una clave derivada y versionada de
  `business_id`, nombre cualificado de operación y clave original. El espacio
  de nombres evita que operaciones o negocios distintos compartan replay.
- El digest v1 se calcula a partir del tipo de comando y de sus campos, sin la
  clave; ordena conjuntos, usa tipos soportados explícitamente y falla ante
  valores no soportados. Una misma clave de ámbito con distinto digest produce
  conflicto; igual digest y resultado válido permiten replay. Una reserva en
  curso no debe ejecutar otra petición.
- El resultado devuelto se valida por tipo, tenant, business e identificador.
  Los eventos y hooks del replay no vuelven a ejecutar los efectos originales.
- Una reserva adquirida se libera si la ejecución falla antes de intentar el
  commit o el adaptador confirma con `CommitNotAppliedError` que no se aplicó.
  Un error de commit de resultado incierto conserva la reserva. Si `complete()`
  falla después de un commit exitoso, tampoco se libera:
  el estado queda incierto y requiere reconciliación. No se promete que un
  fallo de red permita distinguir siempre si un commit fue aplicado.
- El port actual **no garantiza atomicidad** entre persistir dominio y completar
  idempotencia, ni publicación durable. El futuro adaptador debe definir la
  transacción o estrategia de recuperación y demostrarla con pruebas reales.
- Sin token de ownership, este contrato no admite expiración automática o
  reasignación de una reserva mientras pueda quedar un ejecutor activo. TTL,
  leases y recuperación de workers requieren un contrato ampliado con ownership
  verificable y operaciones atómicas, además de pruebas de concurrencia.

## Compatibilidad y transición

Los identificadores de storage y el digest cambian respecto de los previos.
Los registros anteriores no se migran automáticamente. Antes de desplegar en
un entorno con datos o reintentos anteriores debe aplicarse una estrategia
verificada de drenaje, reconciliación, migración o expiración segura. Véase
[plan de transición v1](../plan_migracion_idempotencia_v1.md).

El nombre cualificado de la clase forma parte del ámbito de operación: renombrar
una clase o moverla de módulo cambia el scope y requiere una estrategia de
migración. La serialización v1 conserva la representación de Decimal; valores
numéricamente iguales con distintas escalas pueden tener huellas diferentes.
No se debe cambiar el algoritmo v1 sin versionarlo y gestionar las entradas
existentes.

## Consecuencias y límites

- La protección depende de un `reserve` atómico y de un adaptador que respete el
  contrato. Las pruebas con fakes no prueban las garantías de producción.
- No se genera una clave automáticamente a partir del payload: dos operaciones
  legítimas con igual contenido podrían colisionar. El canal debe identificar el
  intento lógico y conservar su clave al reintentarlo.
- La cobertura, migración, concurrencia real y coherencia con la infraestructura
  de fase 0.5 se validarán antes de declarar el sistema apto para producción.
