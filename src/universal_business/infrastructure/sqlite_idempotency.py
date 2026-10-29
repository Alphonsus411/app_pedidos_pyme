"""Idempotencia SQLite experimental para operaciones de reservas.

El registro RESERVED comparte la transacción de dominio; DONE se escribe
después del commit, tal como exige el orquestador actual. Una caída entre
ambas operaciones deja RESERVED para reconciliación; no existe TTL. Cada
instancia debe pertenecer a una sola ejecución y usar la conexión del UoW.
"""

import json
import sqlite3
from secrets import token_urlsafe
from typing import Any

from universal_business.application.idempotency import IdempotencyKey
from universal_business.application.reservations.cancellation import ReservationCancellation
from universal_business.application.reservations.creation import ReservationDraftCreated
from universal_business.application.reservations.handlers import ReservationConfirmation
from universal_business.application.reservations.status_change import ReservationStatusResult
from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    ReservationId,
    ResourceId,
    TenantId,
)


def create_sqlite_idempotency_schema(connection: sqlite3.Connection) -> None:
    """Crear esquema inicial; no realiza migración de registros previos."""
    connection.execute("""CREATE TABLE IF NOT EXISTS idempotency (
        tenant_id TEXT NOT NULL, key TEXT NOT NULL, digest TEXT NOT NULL,
        token TEXT NOT NULL, state TEXT NOT NULL CHECK (state IN ('reserved', 'done')),
        result TEXT, PRIMARY KEY (tenant_id, key)
    )""")


def _encode(result: object) -> str:
    if type(result) not in (
        ReservationDraftCreated,
        ReservationConfirmation,
        ReservationCancellation,
        ReservationStatusResult,
    ):
        raise ValueError("Resultado no soportado por idempotencia SQLite")
    assert isinstance(
        result,
        (
            ReservationDraftCreated,
            ReservationConfirmation,
            ReservationCancellation,
            ReservationStatusResult,
        ),
    )
    data = {
        "version": 1,
        "tenant": str(result.tenant_id),
        "business": str(result.business_id),
        "location": str(result.location_id),
        "reservation": str(result.reservation_id),
        "resource": str(result.resource_id),
    }
    if type(result) is not ReservationDraftCreated:
        data["version"] = 2
        data["kind"] = {
            ReservationConfirmation: "confirmation",
            ReservationCancellation: "cancellation",
            ReservationStatusResult: "status",
        }[type(result)]
        if isinstance(result, ReservationStatusResult):
            if not isinstance(result.status, ReservationStatus):
                raise ValueError("Estado de reserva inválido")
            data["status"] = result.status.value
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def _decode(payload: str) -> object:
    data = json.loads(payload)
    if type(data) is not dict or type(data.get("version")) is not int:
        raise ValueError("Resultado de idempotencia inválido")
    base = {"version", "tenant", "business", "location", "reservation", "resource"}
    version = data["version"]
    result_type: type[
        ReservationDraftCreated
        | ReservationConfirmation
        | ReservationCancellation
        | ReservationStatusResult
    ]
    if version == 1 and set(data) == base:
        result_type = ReservationDraftCreated
    elif version == 2 and data.get("kind") in ("confirmation", "cancellation", "status"):
        kind = data["kind"]
        expected = base | {"kind"} | ({"status"} if kind == "status" else set())
        if set(data) != expected:
            raise ValueError("Resultado de idempotencia inválido")
        result_type = {
            "confirmation": ReservationConfirmation,
            "cancellation": ReservationCancellation,
            "status": ReservationStatusResult,
        }[kind]
    else:
        raise ValueError("Resultado de idempotencia inválido")
    fields: dict[str, Any] = dict(
        tenant_id=TenantId.from_raw(data["tenant"]),
        business_id=BusinessId.from_raw(data["business"]),
        location_id=LocationId.from_raw(data["location"]),
        reservation_id=ReservationId.from_raw(data["reservation"]),
        resource_id=ResourceId.from_raw(data["resource"]),
    )
    if result_type is ReservationStatusResult:
        return ReservationStatusResult(**fields, status=ReservationStatus(data["status"]))
    return result_type(**fields)


class SqliteReservationIdempotencyStore:
    """Almacén por ejecución para resultados explícitos de reservas.

    El token privado limita complete/release a la ejecución que reservó la
    clave. La conexión no se cierra. No usar como almacén general ni compartir
    instancias entre ejecuciones concurrentes. No garantiza atomicidad entre
    commit del dominio y complete ni resuelve reconciliación automática.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._owned: dict[tuple[str, str], str] = {}

    def get(self, tenant_id: TenantId, key: IdempotencyKey, /) -> tuple[str, object] | None:
        row = self._connection.execute(
            "SELECT digest, result FROM idempotency WHERE tenant_id=? AND key=? AND state='done'",
            (str(tenant_id), key.value),
        ).fetchone()
        return (str(row[0]), _decode(row[1])) if row else None

    def reserve(self, tenant_id: TenantId, key: IdempotencyKey, request_digest: str, /) -> bool:
        if (
            not self._connection.in_transaction
            or getattr(self._connection, "autocommit", None) is True
        ):
            raise RuntimeError("La reserva exige transacción UoW activa")
        identity = (str(tenant_id), key.value)
        token = token_urlsafe(32)
        result = self._connection.execute(
            "INSERT INTO idempotency (tenant_id,key,digest,token,state) VALUES (?,?,?,?, 'reserved') "
            "ON CONFLICT(tenant_id,key) DO NOTHING",
            (*identity, request_digest, token),
        )
        if result.rowcount == 1:
            self._owned[identity] = token
            return True
        return False

    def complete(
        self,
        tenant_id: TenantId,
        key: IdempotencyKey,
        request_digest: str,
        result_object: object = None,
        /,
    ) -> None:
        identity = (str(tenant_id), key.value)
        token = self._owned.get(identity)
        if token is None or self._connection.in_transaction:
            raise RuntimeError("Complete requiere reserva propia y transacción postcommit nueva")
        if getattr(self._connection, "autocommit", None) is True:
            raise RuntimeError("autocommit=True no es compatible")
        encoded = _encode(result_object)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            updated = self._connection.execute(
                "UPDATE idempotency SET state='done', result=? "
                "WHERE tenant_id=? AND key=? AND token=? AND digest=? AND state='reserved'",
                (encoded, *identity, token, request_digest),
            )
            if updated.rowcount != 1:
                raise RuntimeError("Reserva de idempotencia no válida o ajena")
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise
        self._owned.pop(identity, None)

    def release(self, tenant_id: TenantId, key: IdempotencyKey, /) -> None:
        identity = (str(tenant_id), key.value)
        token = self._owned.get(identity)
        if token is None:
            return
        if getattr(self._connection, "autocommit", None) is True:
            raise RuntimeError("autocommit=True no es compatible")
        own_transaction = not self._connection.in_transaction
        try:
            if own_transaction:
                self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                "DELETE FROM idempotency WHERE tenant_id=? AND key=? AND token=? AND state='reserved'",
                (*identity, token),
            )
            if own_transaction:
                self._connection.commit()
        except BaseException:
            if own_transaction:
                self._connection.rollback()
            raise
        self._owned.pop(identity, None)
