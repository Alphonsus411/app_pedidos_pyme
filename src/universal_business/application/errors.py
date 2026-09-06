"""Errores de capa aplicación (Gate 0.2 Foundation).

Se mantiene una jerarquía mínima y plana. NO duplicamos errores de dominio que ya
viven en :mod:`universal_business.domain.shared.errors`.
"""

from __future__ import annotations


class ApplicationError(Exception):
    """Error base para errores detectados en la capa de aplicación.

    Errores de dominio heredan de ``DomainError``; los de aplicación de esta
    clase para que sea sencillo distinguir fronteras en logs / tests / handlers
    de capa superior sin ``contextvars`` mágicos.
    """


class HandlerNotFoundError(ApplicationError):
    """Se solicita manejar un mensaje (command/query/evento) y NO hay ningún
    handler registrado y la semántica del dispatcher es estricta.

    El ``DomainEventDispatcher`` por defecto de Gate 0.2 usa NO-OP y NUNCA
    lanza esta excepción; se reserva para dispatchers estrictos en fases
    posteriores, o para handlers de command/query que exijan resolución.
    """


class IdempotencyConflictError(ApplicationError):
    """Una operación con ``(tenant_id, idempotency_key)`` ya fue procesada.

    El store de idempotencia devolvió ``False`` al intentar ``reserve(...)``;
    el orquestador de la capa aplicación debe interceptar y devolver el
    resultado original (o re-lanzar según semántica adoptada en el use case).
    """


__all__ = [
    "ApplicationError",
    "HandlerNotFoundError",
    "IdempotencyConflictError",
]
