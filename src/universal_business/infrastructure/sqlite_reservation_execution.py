"""Ensamblaje transaccional de casos de uso de reservas SQLite."""

import sqlite3
from collections.abc import Sequence
from typing import Protocol, TypeVar

from universal_business.application.events.dispatcher import DomainEventDispatcher
from universal_business.application.events.publisher import EventPublisher
from universal_business.application.events.reservation_codec import ReservationEventJsonCodec
from universal_business.application.execution import (
    IdempotentReplay,
    UseCaseHandler,
    execute_use_case,
)
from universal_business.application.idempotency import IdempotencyKey, scoped_idempotency_key
from universal_business.application.request_digest import request_digest
from universal_business.application.reservations.cancellation import (
    CancelReservationHandler,
    ReservationCancellation,
)
from universal_business.application.reservations.commands import (
    CancelReservation,
    CheckInReservation,
    CompleteReservation,
    ConfirmReservation,
    CreateReservation,
    MarkReservationNoShow,
)
from universal_business.application.reservations.creation import (
    CreateReservationHandler,
    ReservationDraftCreated,
)
from universal_business.application.reservations.handlers import (
    ConfirmReservationHandler,
    ReservationConfirmation,
)
from universal_business.application.reservations.status_change import (
    CheckInPolicy,
    CheckInReservationHandler,
    CompleteReservationHandler,
    MarkReservationNoShowHandler,
    NoShowPolicy,
    ReservationStatusResult,
)
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import BusinessId, TenantId
from universal_business.infrastructure.sqlite_customers import SqliteCustomerRepository
from universal_business.infrastructure.sqlite_idempotency import SqliteReservationIdempotencyStore
from universal_business.infrastructure.sqlite_locations import SqliteLocationRepository
from universal_business.infrastructure.sqlite_outbox import SqliteOutboxWriter
from universal_business.infrastructure.sqlite_reservation_allocation import (
    SqliteReservationAllocation,
)
from universal_business.infrastructure.sqlite_reservations import (
    SqliteReservationMutationGuard,
    SqliteReservationRepository,
)
from universal_business.infrastructure.sqlite_resources import SqliteResourceRepository
from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork


class _ReservationCommand(Protocol):
    @property
    def tenant_id(self) -> TenantId: ...

    @property
    def business_id(self) -> BusinessId: ...

    @property
    def idempotency_key(self) -> IdempotencyKey: ...


InputT = TypeVar("InputT", bound=_ReservationCommand)
OutputT = TypeVar("OutputT")


class SqliteReservationExecution:
    """Crea puertos por ejecución usando una única conexión y UoW.

    Para desarrollo/pruebas: no abre ni cierra la conexión ni instala esquemas.
    Cada llamada requiere conexión sin transacción. No es una frontera pública:
    el caller debe autenticar y autorizar cada comando, también los replays.
    No impide escrituras externas que evadan los contratos de protección.
    La idempotencia nueva se completa en la misma transacción del dominio y
    outbox. Los registros RESERVED anteriores requieren reconciliación manual.
    La outbox requiere un worker de entrega.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        dispatcher: DomainEventDispatcher,
        publisher: EventPublisher,
        check_in_policy: CheckInPolicy | None = None,
        no_show_policy: NoShowPolicy | None = None,
    ) -> None:
        self._connection = connection
        self._dispatcher = dispatcher
        self._publisher = publisher
        self._check_in_policy = check_in_policy
        self._no_show_policy = no_show_policy

    def _run(
        self,
        command: InputT,
        handler: UseCaseHandler[InputT, OutputT],
        uow: SqliteUnitOfWork,
        store: SqliteReservationIdempotencyStore,
    ) -> OutputT:
        # Este wrapper solo se usa con handlers de reservas conocidos cuyos hooks
        # únicamente completan/liberan idempotencia. No ejecuta hooks genéricos.
        class AtomicHandler:
            def handle(self, input: InputT, /) -> tuple[OutputT, Sequence[DomainEvent]]:
                outcome = handler.handle(input)
                if not isinstance(outcome, IdempotentReplay):
                    result, _events = outcome
                    key = scoped_idempotency_key(
                        business_id=input.business_id,
                        operation=f"{type(input).__module__}.{type(input).__qualname__}",
                        key=input.idempotency_key,
                    )
                    store.complete_in_uow(uow, input.tenant_id, key, request_digest(input), result)
                return outcome

        return execute_use_case(
            handler=AtomicHandler(),
            input=command,
            unit_of_work=uow,
            event_dispatcher=self._dispatcher,
            event_publisher=self._publisher,
            outbox_writer=SqliteOutboxWriter(
                connection=self._connection, encoder=ReservationEventJsonCodec()
            ),
        )

    def create(self, command: CreateReservation) -> ReservationDraftCreated:
        uow = SqliteUnitOfWork(self._connection)
        store = SqliteReservationIdempotencyStore(self._connection)
        handler = CreateReservationHandler(
            reservations=SqliteReservationRepository(self._connection),
            customers=SqliteCustomerRepository(self._connection),
            locations=SqliteLocationRepository(self._connection),
            resources=SqliteResourceRepository(self._connection),
            idempotency=store,
        )
        return self._run(command, handler, uow, store)

    def confirm(self, command: ConfirmReservation) -> ReservationConfirmation:
        uow = SqliteUnitOfWork(self._connection)
        store = SqliteReservationIdempotencyStore(self._connection)
        handler = ConfirmReservationHandler(
            reservations=SqliteReservationRepository(self._connection),
            customers=SqliteCustomerRepository(self._connection),
            allocation=SqliteReservationAllocation(uow),
            idempotency=store,
        )
        return self._run(command, handler, uow, store)

    def cancel(self, command: CancelReservation) -> ReservationCancellation:
        uow = SqliteUnitOfWork(self._connection)
        store = SqliteReservationIdempotencyStore(self._connection)
        handler = CancelReservationHandler(
            reservations=SqliteReservationRepository(self._connection),
            guard=SqliteReservationMutationGuard(uow),
            idempotency=store,
        )
        return self._run(command, handler, uow, store)

    def check_in(self, command: CheckInReservation) -> ReservationStatusResult:
        uow = SqliteUnitOfWork(self._connection)
        store = SqliteReservationIdempotencyStore(self._connection)
        handler = CheckInReservationHandler(
            reservations=SqliteReservationRepository(self._connection),
            guard=SqliteReservationMutationGuard(uow),
            idempotency=store,
            check_in_policy=self._check_in_policy,
        )
        return self._run(command, handler, uow, store)

    def complete(self, command: CompleteReservation) -> ReservationStatusResult:
        uow = SqliteUnitOfWork(self._connection)
        store = SqliteReservationIdempotencyStore(self._connection)
        handler = CompleteReservationHandler(
            reservations=SqliteReservationRepository(self._connection),
            guard=SqliteReservationMutationGuard(uow),
            idempotency=store,
        )
        return self._run(command, handler, uow, store)

    def no_show(self, command: MarkReservationNoShow) -> ReservationStatusResult:
        uow = SqliteUnitOfWork(self._connection)
        store = SqliteReservationIdempotencyStore(self._connection)
        handler = MarkReservationNoShowHandler(
            reservations=SqliteReservationRepository(self._connection),
            guard=SqliteReservationMutationGuard(uow),
            idempotency=store,
            no_show_policy=self._no_show_policy,
        )
        return self._run(command, handler, uow, store)
