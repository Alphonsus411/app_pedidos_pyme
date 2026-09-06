"""Contratos de idempotencia.

Objetivo: proteger operaciones (commands, webhook callbacks, mensajes de
broker duplicados, etc.) de ser procesadas más de una vez por
``(tenant_id, idempotency_key)``.

El diseño es **mínimo y sin infraestructura** (0.2 Foundation):
- :class:`IdempotencyKey`  identificador semántico simple (string válidado).
- :class:`IdempotencyStore` Protocol para futuras implementaciones.

### Semántica adoptada

Todo flujo de trabajo típico::

    # 1) Anticipadamente: el cliente genera una key unívoca (UUID o similar).
    if not store.reserve(tenant_id, key, digest(request)):
        # O bien está siendo procesado por otro worker, o ya se completó.
        return store.get(tenant_id, key).cached_result

    try:
        # 2) Dentro de UnitOfWork: ejecutar comando (orquestación + dominio).
        result = handler(command)

        # 3) commit() del UoW.
        # 4) almacenar resultado y marcar como COMPLETADO.
        store.complete(tenant_id, key, digest(result), result)
        return result
    except Exception:
        # 5) Fallo antes de complete: liberar la reserva para reintentos.
        store.release(tenant_id, key)
        raise

- **``tenant_id`` siempre explícito**: las keys son independientes por tenant
  (no hay riesgo de cross-tenant colisiones aunque los UUID coincidan entre
  tenants por error).
- No asumimos timeouts, TTLs, ni limpieza automática en esta fase. Eso lo
  implementará el adapter de infraestructura concreta.

### Recuperación tras fallo (``release``)

Una operación que haya reservado una key con :meth:`IdempotencyStore.reserve`
y falle **antes** de llamar a :meth:`IdempotencyStore.complete` debe invocar
:meth:`IdempotencyStore.release` para devolver la key al estado ``FREE`` y
permitir reintentos posteriores. Sin :meth:`release` la key permanecería
``RESERVED`` indefinidamente (0.2 no asume TTL automático).

Semántica contractual de :meth:`release`:

- ``FREE``     → no-op (idempotente, no error).
- ``RESERVED`` → vuelve a ``FREE``.
- ``DONE``     → no-op (jamás se libera una operación completada).
- Siempre exige ``tenant_id`` explícito (aislamiento por tenant).

"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from universal_business.domain.shared.value_objects.ids import TenantId

# Se aceptan caracteres alfanuméricos, guiones y guiones bajos. Longitud 8..128.
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


class InvalidIdempotencyKeyError(ValueError):
    """Formato de IdempotencyKey no permitido (longitud/caracteres)."""


@dataclass(frozen=True, kw_only=True)
class IdempotencyKey:
    """Wrapper semántico inmutable sobre un str validado.

    Evita que un :class:`str` cualquiera pase por error como key (ej: un
    nombre de command, un aggregate ID) y genere falsos positivos en
    idempotencia.
    """

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise InvalidIdempotencyKeyError(
                f"IdempotencyKey.value debe ser str, got {type(self.value).__name__}"
            )
        if not _KEY_PATTERN.fullmatch(self.value):
            raise InvalidIdempotencyKeyError(
                f"IdempotencyKey.value inválido: {self.value!r}."
                " Formato admitido: [A-Za-z0-9_-]{8,128}."
            )

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@runtime_checkable
class IdempotencyStore(Protocol):
    """Port abstracto para idempotencia.

    Todos los métodos **exigen** ``tenant_id`` explícito para respetar la
    estrategia de aislamiento por tenant. Los adapters con implementación
    real (DB, Redis, Outbox) vendrán en Gate 0.5+.
    """

    # ------------------------------------------------------------------
    # Estados lógicos internos (cada adapter los implementa)
    #   FREE     → key nunca vista
    #   RESERVED → key está siendo procesada (llamada reserve() exitosa)
    #   DONE     → key completada (complete() exitoso)
    # ------------------------------------------------------------------

    def get(
        self,
        tenant_id: TenantId,
        key: IdempotencyKey,
        /,
    ) -> tuple[str, object] | None:
        """Lee el resultado previamente almacenado.

        Returns
        -------
        ``(request_digest, result_object)`` para una key ya completada,
        o ``None`` si la key no existe o todavía está reservada.
        """
        raise NotImplementedError

    def reserve(
        self,
        tenant_id: TenantId,
        key: IdempotencyKey,
        request_digest: str,
        /,
    ) -> bool:
        """Intenta reservar la key para empezar el procesamiento.

        Returns
        -------
        ``True``  → reserva OK (procesamiento puede empezar).
        ``False`` → la key ya estaba RESERVED o DONE (devolver caché desde
        :meth:`get` o lanzar :class:`IdempotencyConflictError` según
        semántica del caso de uso).
        """
        raise NotImplementedError

    def complete(
        self,
        tenant_id: TenantId,
        key: IdempotencyKey,
        result_digest: str,
        result_object: object = None,
        /,
    ) -> None:
        """Marca key como DONE y almacena (digest, result_object).

        Después de ``complete``, :meth:`reserve` sobre la misma
        ``(tenant_id, key)`` devolverá ``False``.
        """
        raise NotImplementedError

    def release(
        self,
        tenant_id: TenantId,
        key: IdempotencyKey,
        /,
    ) -> None:
        """Libera una reserva previa (``RESERVED`` → ``FREE``).

        Semántica contractual:

        - Estado ``FREE`` (key inexistente): **no-op idempotente** (no error).
        - Estado ``RESERVED``: vuelve a ``FREE`` (puede volver a reservarse).
        - Estado ``DONE`` (key ya completada): **no-op seguro** (jamás se
          deshace una operación terminada; :meth:`release` se convierte en
          silencioso).

        Debe invocarse si el handler o el UnitOfWork fallan **antes** de
        llamar a :meth:`complete`, para evitar que la key quede
        indefinidamente ``RESERVED`` (Gate 0.2 no asume TTL).
        """
        raise NotImplementedError


__all__ = [
    "IdempotencyKey",
    "IdempotencyStore",
    "InvalidIdempotencyKeyError",
]
