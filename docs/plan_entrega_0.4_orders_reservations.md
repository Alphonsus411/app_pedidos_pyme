# Plan de entrega 0.4 — Pedidos, reservas y disponibilidad mínima

**Estado:** propuesta para revisión; no supone aprobación del Gate 0.4.
**Fecha:** 28-oct-2026.
**Baseline:** `master` en `a33176e27c651f96806f8d28dca447ceada86f24` (Gate 0.3 y PR #2 integrados).
**Rama de planificación:** `feat/fase-3-orders-reservations`.
**Objetivo:** desarrollar un núcleo de pedidos y reservas agnóstico de vertical, verificable offline y compatible con los contratos existentes.

## 1. Punto de partida y límites

- Gate 0.3 proporciona Offering, categorías, requisitos de recursos, Resource y ResourceType, casos de uso de catálogo y recursos, UoW, eventos y contratos de idempotencia.
- Order contiene actualmente tenant, business, location, canal, estado y total opcional, sin líneas ni cálculo; Reservation contiene cliente, recurso, localización, rango y estado, sin reglas de reserva completas.
- AvailabilityRule y AvailabilityBlock son esqueletos: no existe motor de agenda ni garantía de concurrencia en una base de datos.
- El puerto actual de idempotencia identifica por tenant y key; ADR-007 describe además business y scope. Es necesario reconciliar ambos antes de asegurar esa semántica.
- El `TimeRange` existente considera ambos extremos inclusivos y admite duración cero. No debe utilizarse su `overlaps` como si fuera semiabierto: §4 propone una política explícita para reservas.

**Fuera de alcance 0.4:** FastAPI, ORM, PostgreSQL, outbox físico, infraestructura de producción, integraciones de pago/canales, interfaz, facturación fiscal o conformidad normativa, inventario, precios dinámicos, recurrencias complejas y una vertical concreta. No se promete seguridad de concurrencia en producción hasta disponer de un adaptador transaccional y pruebas de integración.

## 2. Decisiones propuestas para aprobación

| ID | Propuesta para el alcance inicial | Efecto / decisión pendiente |
|---|---|---|
| D1 | Pedido con líneas de Offering, cantidades positivas y precio unitario capturado. Una moneda por pedido. | Resolver compatibilidad de la entidad actual y política para Offering sin precio. |
| D2 | Descuento e impuesto explícitos por línea, opcionales y limitados a importes o porcentajes simples; no hay motor de reglas ni liquidación fiscal. | Acordar modalidad exacta, límites y datos necesarios antes de implementar. |
| D3 | Reserva de un recurso explícito por Location y Customer, con intervalo aware y de duración positiva. | Recurso sin location: exigir una política explícita de elegibilidad antes de habilitarlo. |
| D4 | Disponibilidad mínima determinista por reglas, bloqueos y reservas confirmadas; sin recurrencias, pools ni asignación automática. | La semántica de horarios y zonas de DateRange requiere diseño explícito. |
| D5 | Conflictos de reserva se detectan dentro de un contrato transaccional de adjudicación atómica. Los fakes verifican el contrato; un repositorio real debe garantizarlo en 0.5. | Una consulta seguida de save no protege de carreras. |
| D6 | Idempotencia obligatoria para creación y confirmación de pedido y reserva. | Resolver ADR-007 frente al puerto actual y definir namespace, digest, concurrencia y recuperación. |

Estas propuestas son un punto de partida. Las decisiones D2, D3, D4 y D6 deben cerrarse en la especificación/ADR de 0.4; no se han presentado como funcionalidades existentes.

## 3. Pedidos: alcance funcional propuesto

### Modelo y cálculo
- Evolucionar el agregado Order con líneas identificables; cada línea referencia un Offering y captura nombre, precio, moneda, cantidad y, si se acuerda D2, ajustes aplicados. Los cambios posteriores al catálogo no alteran el snapshot.
- Validar tenant, business y location para pedido, Offering y cliente cuando exista. Validar que Offering esté activo y disponible para la localización conforme a su alcance.
- Cantidades estrictamente positivas, representación numérica acordada y sin float; importes no negativos, moneda única y descuentos no superiores a su base. No confiar en totales enviados por el llamador.
- Cálculo propuesto: subtotal de líneas; descuento limitado; impuesto calculado sobre la base después del descuento; total = subtotal − descuentos + impuestos. Definir si impuestos son incluidos o añadidos, precisión de porcentaje y redondeo por línea antes de implementar. `Money` usa Decimal, escala 4 y ROUND_HALF_EVEN; 0.4 no debe afirmar que esta política equivale al redondeo legal de moneda o a una factura.
- Definir explícitamente cuándo se congelan las líneas y totales y cómo se conserva el histórico después de confirmar.

### Ciclo de vida
El enum actual tiene DRAFT, VALIDATED, CONFIRMED, PREPARING, READY, DELIVERING, COMPLETED y CANCELLED. La matriz inicial propuesta es:

| Origen | Destinos permitidos |
|---|---|
| DRAFT | VALIDATED, CANCELLED |
| VALIDATED | DRAFT, CONFIRMED, CANCELLED |
| CONFIRMED | PREPARING, CANCELLED |
| PREPARING | READY, CANCELLED |
| READY | DELIVERING, COMPLETED, CANCELLED |
| DELIVERING | COMPLETED, CANCELLED |
| COMPLETED / CANCELLED | Ninguno |

Cada transición se valida y emite su evento solo cuando cambia el estado. No asumir que todas las verticales necesitan cada estado; recorridos abreviados adicionales requieren decisión explícita. Validar al menos una línea y totales coherentes antes de confirmar. La cancelación no implica por sí misma reembolso, stock ni envío.

## 4. Reservas y disponibilidad mínima

### Ciclo de vida propuesto
`DRAFT → CONFIRMED → CHECKED_IN → COMPLETED`; desde DRAFT o CONFIRMED se puede cancelar; desde CONFIRMED se puede registrar NO_SHOW. CANCELLED, NO_SHOW y COMPLETED son terminales. Se concretarán requisitos y reglas temporales sin inferirlas de la hora del sistema; usar reloj inyectable si son necesarias.

### Semántica temporal
- Para adjudicación, proponer intervalos semiabiertos `[inicio, fin)`: reservas contiguas no se solapan; duración debe ser positiva y los extremos aware se comparan como instantes UTC.
- `TimeRange.overlaps` actual es inclusivo; introducir una operación específica o un tipo apropiado y pruebas de compatibilidad, sin alterar silenciosamente la semántica compartida.
- Reglas horarias y bloques necesitan una zona IANA explícita de la Location o entrada equivalente: definir tratamiento de DST, horas inexistentes y ambiguas antes de implementarlos. DateRange es inclusivo por fechas y no debe confundirse con el intervalo horario.
- El motor propuesto comprueba recurso activo, scope y localización; ventana aplicable; bloqueos; reservas confirmadas solapadas y capacidad. Definir en la especificación precedencia entre reglas y comportamiento cuando no existan reglas; no asumir disponibilidad por defecto.
- Para esta primera entrega se propone exclusividad por Resource: una reserva confirmada ocupa el recurso completo; `party_size` positivo no puede superar `Resource.capacity` si se define. No se promete capacidad compartida ni cálculo de capacidad residual de pools.
- Cancelar libera ocupación a efectos de consultas posteriores; DRAFT no bloquea. Cambio de horario, reasignación y reservas de múltiples recursos quedan fuera salvo ampliación formal del plan.

### Concurrencia: condición indispensable
El contrato de confirmación debe combinar comprobación de disponibilidad y adjudicación dentro de la misma frontera transaccional, serializando o rechazando conflictos. Un test con fake coordinado debe demostrar que dos intentos incompatibles producen como máximo una confirmación. Ese test demuestra el contrato del fake, **no** seguridad de PostgreSQL u otro adaptador. Gate 0.5 debe incluir prueba de integración con transacciones concurrentes reales, estrategia de aislamiento/lock o restricción y recuperación de fallos.

## 5. Aplicación, aislamiento y eventos

- Commands/queries tipados y handlers para crear, consultar, modificar y confirmar pedidos; crear, consultar, confirmar, cancelar y actualizar estado de reservas; consultas de disponibilidad según alcance aprobado.
- Toda operación utiliza tenant explícito; validar business y location en entidades relacionadas incluso cuando un repositorio devuelva un objeto fuera de scope. Los casos negativos no deben guardar cambios ni publicar eventos.
- Reutilizar `execute_use_case`, UoW y hooks sin estado por ejecución; definir eventos inmutables con IDs y contexto mínimo. Despachar/publicar solo tras commit; fallo precommit provoca rollback y no publicación.
- Idempotencia: igual clave y misma solicitud devuelve el resultado previo; misma clave con solicitud distinta devuelve conflicto; una operación en curso no ejecuta duplicados. Las keys deben quedar aisladas por tenant, business y operación conforme a la decisión final D6.
- Revisar la discrepancia entre ADR-007 y `IdempotencyStore(tenant_id, key)`, incluido el significado de digest de solicitud/resultado. Documentar y probar el contrato elegido antes de añadir handlers. No asumir que el namespace aporta atomicidad por sí mismo.
- Caso crítico: commit del dominio correcto y fallo de `complete`: no liberar la key ni volver a ejecutar ciegamente; propagar/registrar el fallo y definir reconciliación. La solución persistente debe tratar la ventana entre commit e idempotencia, además del outbox, en 0.5.

## 6. Desglose secuencial de trabajo

| Orden | Tarea | Entregable y condición de salida |
|---|---|---|
| T0 | Revisar y aprobar D1–D6; resolver contradicciones con ADR-006/007 y contratos existentes. | Especificación y ADRs actualizados, sin cambios de código prematuros. |
| T1 | Especificar matrices de transición y modelo monetario. | Reglas de cálculo, límites, snapshot y pruebas de aceptación acordadas. |
| T2 | Implementar dominio de pedidos y eventos. | Agregado, líneas, invariantes, transiciones y tests de dominio. |
| T3 | Implementar dominio de reservas y política temporal. | Estados, intervalos positivos, scope y tests de límites/DST acordados. |
| T4 | Diseñar disponibilidad mínima y puerto de adjudicación atómica. | Algoritmo puro y contrato transaccional documentados; fake coordinado. |
| T5 | Casos de uso de pedidos y reservas. | Commands/queries, handlers, validaciones de ámbito y eventos. |
| T6 | Resolver idempotencia y semántica de errores con UoW. | Contratos coherentes, pruebas de reintentos, rollback y fallo postcommit. |
| T7 | Verificación arquitectónica e integración offline. | CI verde, pruebas de regresión y evidencias por criterio. |
| T8 | Documentación final y revisión de gate. | Estado, decisiones, limitaciones y evidencias; aprobación humana antes de 0.5. |

T2 y T3 pueden desarrollarse independientemente tras T0/T1; T4 y T6 deben quedar cerrados antes de considerar la confirmación de reservas terminada. No se crea una etiqueta ni se cambia la versión como parte de este plan.

## 7. Criterios de aceptación del Gate 0.4

- **AC1 Pedidos:** creación y edición en estados permitidos; snapshot independiente del catálogo; al menos una línea válida para confirmar; matriz completa de transiciones positivas y negativas.
- **AC2 Dinero:** cálculo reproducible con Decimal y misma moneda; se rechazan float, cantidades inválidas, descuentos excesivos y monedas mezcladas; pruebas de redondeo, límites y totales.
- **AC3 Reservas:** transición y terminalidad de cada estado; cliente, recurso y location válidos; prueba de intervalos contiguos, solapados, vacíos y zonas horarias conforme a la decisión aprobada.
- **AC4 Disponibilidad:** reglas, bloqueos, estado del recurso, capacidad individual y reservas confirmadas evaluados conforme a políticas explícitas; ausencia de reglas y precedencia probadas.
- **AC5 Concurrencia:** fake transaccional demuestra como máximo una confirmación en dos intentos solapados; limitación de adapter real registrada y prueba real obligatoria en 0.5.
- **AC6 Aislamiento:** intentos cross-tenant, cross-business y cross-location rechazados sin efectos secundarios; consultas no filtran datos de otros ámbitos.
- **AC7 Idempotencia:** replay, digest diferente, operación concurrente, fallo de handler/commit y fallo de complete tras commit probados para operaciones acordadas; reconciliación y límites documentados.
- **AC8 Eventos y transacciones:** sin eventos publicados si falla commit; eventos coherentes tras éxito; escenarios postcommit definidos sin afirmar entrega durable.
- **AC9 Regresión:** `python -m pytest -q`, `ruff check .`, `ruff format --check .`, `mypy src` y `git diff --check` exitosos; CI Python 3.11 y 3.12 verde, sin regresiones de arquitectura y sin dependencias runtime nuevas.
- **AC10 Cierre:** matriz de evidencia y desviaciones, ADRs y documentación actualizados; aprobación humana del gate. No se declara listo para producción por pasar pruebas offline.

## 8. Riesgos y asuntos pendientes

1. **Idempotencia:** el port actual y ADR-007 difieren en scope; además la finalización postcommit no es atómica con el dominio. Resolver diseño y reconciliación explícitamente.
2. **Reservas concurrentes:** los tests de dominio no demuestran el aislamiento de almacenamiento. Bloqueante de operación real hasta 0.5.
3. **Fecha, hora y DST:** la semántica inclusiva de TimeRange no coincide con la propuesta semiabierta; DateRange no modela zona horaria.
4. **Precios e impuestos:** el redondeo interno no es por sí solo una política fiscal; los ajustes no representan facturación legal.
5. **Modelo universal:** los estados PREPARING/DELIVERING y reservas de recurso único pueden no encajar en todas las verticales. Validar generalidad sin introducir reglas sectoriales.
6. **Compatibilidad:** identificar usos del skeleton, ports y tests antes de cambiar firmas y documentar la estrategia de migración.
7. **Offering sin precio y recurso business-wide:** decidir explícitamente cómo tratarlos antes de confirmar casos de uso.

## 9. Cierre y siguiente acción

Revisar este borrador, adoptar o modificar D1–D6 y producir la especificación detallada antes de implementar. El plan se basa en el código y documentos disponibles en el baseline citado; no se han ejecutado ni implementado las tareas 0.4.
