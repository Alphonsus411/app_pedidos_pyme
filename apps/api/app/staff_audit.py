"""Puerto mínimo de auditoría de lecturas staff en el adaptador HTTP.

No persiste eventos ni registra credenciales. La implementación del sumidero
y su durabilidad son responsabilidad de la composición del entorno.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class StaffAccessAuditEvent:
    request_id: str
    subject: str | None
    business_slug: str
    location_slug: str
    action: str
    status_code: int


class StaffAuditSink(Protocol):
    def record(self, event: StaffAccessAuditEvent) -> None:
        """Recibir el resultado del acceso sin tokens ni IDs de pedidos."""
        ...
