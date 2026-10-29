"""Frontera transaccional SQLite para el prototipo."""

import sqlite3
from types import TracebackType
from typing import Self


class SqliteUnitOfWork:
    """Una transacción de un solo uso sobre una conexión propiedad del caller.

    Repositorios y outbox deben recibir esta misma conexión. Se usa BEGIN
    IMMEDIATE para obtener el bloqueo de escritura antes de leer y modificar.
    No cierra la conexión, no permite anidamiento y nunca confirma al salir.
    Un error de commit conserva su resultado como incierto; rollback posterior
    no prueba que el commit no se haya aplicado.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self._state = "new"

    def __enter__(self) -> Self:
        if self._state != "new" or self.connection.in_transaction:
            raise RuntimeError("Se requiere UoW nueva y conexión sin transacción")
        if getattr(self.connection, "autocommit", None) is True:
            raise RuntimeError("autocommit=True no es compatible con esta UoW")
        self.connection.execute("BEGIN IMMEDIATE")
        self._state = "active"
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
        /,
    ) -> None:
        if self._state in ("active", "commit_failed"):
            self.rollback()
        self._state = "closed"

    def commit(self) -> None:
        if self._state == "committed":
            return
        if self._state != "active":
            raise RuntimeError("No hay una transacción activa")
        try:
            self.connection.commit()
        except BaseException:
            self._state = "commit_failed"
            raise
        self._state = "committed"

    def rollback(self) -> None:
        if self._state in ("rolled_back", "committed", "closed"):
            return
        if self._state not in ("active", "commit_failed"):
            raise RuntimeError("No hay una transacción activa")
        self.connection.rollback()
        self._state = "rolled_back"
