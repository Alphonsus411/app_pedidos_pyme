"""Errores compartidos por todo el dominio (Entrega 0.1).

Cada módulo de dominio puede extender o definir sus propios errores específicos.
"""

from __future__ import annotations


class DomainError(Exception):
    """Error base para todos los errores lanzados desde el dominio."""


class InvariantViolationError(DomainError):
    """Un invariante de dominio no se cumple."""


# ---------- Money ----------
class MoneyError(DomainError):
    pass


class MoneyCurrencyMismatchError(MoneyError):
    """Operación con monedas distintas (o moneda inválida)."""


class MoneyRoundingError(MoneyError):
    """Error de redondeo inseguro o operación inválida."""


# ---------- Temporal ----------
class TemporalError(DomainError):
    pass


class TemporalRangeError(TemporalError):
    """Error en construcción o operación de rangos temporales.

    Incluye datetime naive cuando se requiere aware, o start > end.
    """


class TimezoneAwareRequiredError(TemporalRangeError):
    """Se recibió un datetime naive cuando se requería timezone-aware."""


# ---------- Status transitions ----------
class StatusError(DomainError):
    pass


class StatusTransitionError(StatusError):
    """Transición de estado no permitida por la máquina de estados del agregado."""


# ---------- Tenancy ----------
class TenancyError(DomainError):
    pass


class TenantBoundaryViolationError(TenancyError):
    """Operación que cruza el límite de aislamiento entre tenants."""
