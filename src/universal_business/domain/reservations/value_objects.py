"""Value objects de Reservations (estados propios del dominio)."""

from __future__ import annotations

from enum import StrEnum


class ReservationStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    CHECKED_IN = "checked_in"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


__all__ = ["ReservationStatus"]
