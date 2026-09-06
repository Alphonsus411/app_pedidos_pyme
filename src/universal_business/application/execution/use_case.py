"""Patrón ejecución de casos de uso (mismo módulo que ``execute_use_case``).

Gate 0.2 Foundation ofrece este módulo de conveniencia para
``from universal_business.application.execution.use_case import execute_use_case``
y también en ``application.execution.__init__`` re-exporta.
"""

from __future__ import annotations

from universal_business.application.execution import (
    InT,
    OutT,
    UseCaseHandler,
    execute_use_case,
)

__all__ = [
    "InT",
    "OutT",
    "UseCaseHandler",
    "execute_use_case",
]
