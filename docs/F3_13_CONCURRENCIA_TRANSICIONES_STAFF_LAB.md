# F3.13 — Concurrencia e idempotencia de transiciones staff (laboratorio)

**Alcance:** pruebas de regresión para el endpoint opt-in F3.11 sobre FastAPI real y SQLite temporal sintético. Se parte de F3.12 (auditoría de mutaciones) como rama de base; no hay cambios de dominio, aplicación, repositorios, frontend ni esquema.

## Casos nuevos

1. Dos clientes HTTP independientes lanzan al mismo tiempo una transición de un único pedido con la **misma** clave idempotente. Se exige 200/200, ambos resultados equivalentes, **una** entrada de idempotencia y **un** evento outbox adicionales.
2. Dos clientes independientes compiten sobre el mismo pedido con **claves distintas**. Se exige 200/409, estado final validado, una sola clave persistida y un solo evento outbox.
3. Dos operadores de negocios diferentes transicionan pedidos diferentes de forma simultánea, cada uno con sesión y prueba CSRF propias. Se exige 200/200, ambos pedidos modificados en sus respectivos ámbitos y dos entradas de idempotencia/outbox adicionales.

Se sincroniza el comienzo de las solicitudes mediante una barrera de hilos. Cada solicitud crea su propio cliente HTTP y el adaptador abre una conexión SQLite por operación. La UoW existente adquiere bloqueo `BEGIN IMMEDIATE` antes de escribir, con idempotencia y outbox dentro de la misma transacción. Las pruebas no añaden reintentos automáticos, `sleep`, ni alteran la política de negocio.

## Criterios y límites

Comprobaciones: códigos, respuesta pública, estado almacenado y variación de contadores de `idempotency` y `transactional_outbox`. Los resultados dependen de la planificación de hilos y el bloqueo SQLite; pasar estas pruebas **no acredita** seguridad de concurrencia bajo varios procesos, caídas, saturación, almacenamiento en red o PostgreSQL. También permanece sin certificar el caso de expiración de timeout y manejo de errores `database is locked` en escenarios de alta contención.

**Pendiente antes de integración:** CI Python 3.11/3.12, pytest, Ruff, mypy y revisión. SQLite solo desarrollo/pruebas, sin identidad real, despliegue ni acceso desde React. La rama precedente F3.12 todavía no está integrada en master; evitar merge de F3.13 que la salte.

## Ejecución

```bash
python -m pytest -q tests/api/test_staff_order_transitions.py
ruff check .
ruff format --check .
mypy src
```
