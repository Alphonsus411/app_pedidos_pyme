"""Contratos para extensiones verticales (mismo contenido que el package init).

Alias conveniencia para imports explícitos por archivo:
``from universal_business.application.extensions.verticals import (VerticalExtension, VerticalRegistry)``
"""

from __future__ import annotations

from universal_business.application.extensions import VerticalExtension, VerticalRegistry

__all__ = [
    "VerticalExtension",
    "VerticalRegistry",
]
