# Plan de transición a idempotencia v1

**Estado: propuesta operativa; sin implementación ni validación con adaptador real.**
**Fecha:** 28-10-2026. Asociado al ADR-007 y al hardening del PR #4.

## Contexto

El contrato anterior usa `(tenant_id, key)`; el nuevo usa tenant explícito y
una clave derivada y versionada de business, operación y key. La huella de
solicitud también cambia. Los dos formatos no se consultan entre sí: activar
v1 sobre un almacén legacy puede aceptar una misma petición como nueva.

No hay en el núcleo 0.3 un adaptador persistente de idempotencia implementado.
No se ha comprobado si existen adaptadores externos, datos reales o clientes
en uso: no se puede concluir que el despliegue sea seguro por su ausencia en
este repositorio.

## Política propuesta: bloqueo hasta reconciliar

1. Inventariar todos los adaptadores, workers y clientes, el volumen de claves
   legacy, sus ámbitos y la ventana máxima de reintentos pactada con cada canal.
   Si no es posible conocerlos, no activar el cambio en ese entorno.
2. Drenar operaciones y pausar admisión de mutaciones idempotentes; impedir
   despliegue mixto de lectores/escritores legacy y v1 durante la transición.
3. Identificar registros RESERVED o de resultado incierto y reconciliarlos con
   el estado real de los agregados y efectos externos. Un RESERVED no se elimina
   por superar una fecha sin confirmar si el dominio ya se confirmó.
4. Para cada DONE, migrar solo si pueden demostrarse tenant, business, operación,
   clave original, solicitud canónica y resultado. Verificar la huella de la
   solicitud y crear la nueva entrada mediante un procedimiento transaccional e
   idempotente de migración propio del adaptador. Detectar colisiones y detener
   la migración si existen diferencias. No reconstruir una huella a partir del
   resultado: no prueba qué solicitud la originó.
5. Si no pueden recuperarse todos esos datos, mantener el bloqueo para esos
   registros. Un eventual retiro por expiración requiere una política explícita
   de retención, fin de ventana de reintentos y reconciliación documentada;
   nunca borrar entradas inciertas como solución automática.
6. Verificar recuentos, paridad, disponibilidad de resultados y replays sin
   efectos secundarios; ensayar interrupción y reanudación de migración. Registrar
   evidencia y activar v1 solo tras completar las comprobaciones.
7. Conservar respaldo verificable y un plan de vuelta atrás que preserve todas
   las operaciones efectuadas bajo v1. No volver simplemente al formato anterior
   después de admitir nuevas operaciones v1: podría duplicarlas.

## Entornos sin registros legacy

Solo se puede arrancar con almacén v1 vacío después de verificar que no existen
registros ni operaciones pendientes de un sistema anterior y que no llegan
reintentos legacy. La verificación corresponde al despliegue, no al core actual.

## Requisitos del futuro adaptador y pruebas

- Reserva atómica por tenant y clave derivada; ownership explícito o mecanismo
  equivalente para impedir que una ejecución libere o complete la reserva ajena,
  especialmente si se introducen TTL, expiración o concurrencia entre procesos.
- Persistir digest original de solicitud y resultado, verificar digest en replay,
  mantener integridad de tenant/business/operación y definir transacciones y
  colisiones. No hay TTL ni tokens de propiedad en el protocolo actual.
- Definir cómo evitar duplicados en la ventana entre commit de dominio y complete
  de idempotencia y cómo recuperar estados inciertos; abordar también outbox y
  entrega de eventos, sin prometer exactamente-una-vez.
- Validar en integración real: reserva y creación concurrentes, crash antes y
  después del commit, complete fallido, reintentos, reinicio, migración parcial,
  rollbacks, colisiones y aislamiento entre tenants, businesses y operaciones.
- Definir versionado estable de identificadores de operación. Usar el nombre
  cualificado de una clase implica que renombrarla cambia el ámbito y requiere
  migración; no hacerlo silenciosamente.

## Condición de cierre

Este documento define una política propuesta, no una migración ejecutada. La
compatibilidad de un entorno solo se considerará cerrada con inventario y
reconciliación verificables, un procedimiento implementado para su adaptador,
ensayos y evidencia. Hasta entonces el hardening no debe presentarse como
seguro para producción con datos existentes.
