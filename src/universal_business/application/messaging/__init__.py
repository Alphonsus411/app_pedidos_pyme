"""Primitivas de mensajería. Gate 0.2 Foundation.

- :mod:`~universal_business.application.messaging.commands` — marcador semántico
  para mensajes de tipo comando (escriben estado).
- :mod:`~universal_business.application.messaging.queries` — marcador semántico
  para mensajes de tipo consulta (solo leen).
- :mod:`~universal_business.application.messaging.handlers` — contratos
  ``CommandHandler`` / ``QueryHandler`` tipados con :pep:`484` generics.
"""

from __future__ import annotations

from universal_business.application.messaging.commands import Command
from universal_business.application.messaging.handlers import (
    CommandHandler,
    QueryHandler,
)
from universal_business.application.messaging.queries import Query

__all__ = [
    "Command",
    "CommandHandler",
    "Query",
    "QueryHandler",
]
