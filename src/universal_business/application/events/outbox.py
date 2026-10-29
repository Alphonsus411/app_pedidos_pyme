"""Puerto de escritura transaccional de eventos, sin adaptador concreto."""

from collections.abc import Sequence
from typing import Protocol

from universal_business.domain.shared.events import DomainEvent


class TransactionalOutboxWriter(Protocol):
    """Escribe eventos en la misma transacción y conexión que el UnitOfWork.

    No debe confirmar la transacción ni publicarlos. El ensamblaje de la
    aplicación debe garantizar la transacción compartida; el protocolo por sí
    solo no puede verificarla. Debe conservar identificadores de evento para
    facilitar deduplicación del consumidor y propagar errores de escritura.
    """

    def write_many(self, events: Sequence[DomainEvent], /) -> None:
        """Persiste el lote dentro de la transacción aún no confirmada."""
        raise NotImplementedError
