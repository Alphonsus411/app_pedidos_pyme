"""Ensamblaje SQLite del ciclo de pedidos."""

import sqlite3
from collections.abc import Sequence
from typing import Protocol, TypeVar, cast

from universal_business.application.events.business_event_codec import BusinessEventJsonCodec
from universal_business.application.events.dispatcher import DomainEventDispatcher
from universal_business.application.events.publisher import EventPublisher
from universal_business.application.execution import (
    IdempotentReplay,
    UseCaseHandler,
    execute_use_case,
)
from universal_business.application.idempotency import IdempotencyKey, scoped_idempotency_key
from universal_business.application.orders.add_line import (
    AddOrderLineHandler,
    OrderLinePolicy,
    OrderLineResult,
)
from universal_business.application.orders.commands import (
    AddOrderLine,
    CancelOrder,
    CompleteOrder,
    ConfirmOrder,
    CreateOrder,
    DispatchOrder,
    MarkOrderReady,
    OrderStatusCommand,
    PrepareOrder,
    RemoveOrderLine,
    ReturnOrderToDraft,
    ValidateOrder,
)
from universal_business.application.orders.creation import CreateOrderHandler, OrderDraftCreated
from universal_business.application.orders.remove_line import (
    OrderLineRemoval,
    RemoveOrderLineHandler,
)
from universal_business.application.orders.status_change import (
    CancelOrderHandler,
    CompleteOrderHandler,
    ConfirmOrderHandler,
    DispatchOrderHandler,
    MarkOrderReadyHandler,
    OrderStatusResult,
    OrderTransitionPolicy,
    PrepareOrderHandler,
    ReturnOrderToDraftHandler,
    ValidateOrderHandler,
)
from universal_business.application.request_digest import request_digest
from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import BusinessId, TenantId
from universal_business.infrastructure.sqlite_customers import SqliteCustomerRepository
from universal_business.infrastructure.sqlite_locations import SqliteLocationRepository
from universal_business.infrastructure.sqlite_offerings import SqliteOfferingRepository
from universal_business.infrastructure.sqlite_order_idempotency import SqliteOrderIdempotencyStore
from universal_business.infrastructure.sqlite_orders import (
    SqliteOrderMutationGuard,
    SqliteOrderRepository,
)
from universal_business.infrastructure.sqlite_outbox import SqliteOutboxWriter
from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork


class _Command(Protocol):
    @property
    def tenant_id(self) -> TenantId: ...
    @property
    def business_id(self) -> BusinessId: ...
    @property
    def idempotency_key(self) -> IdempotencyKey: ...


InputT = TypeVar("InputT", bound=_Command)
OutputT = TypeVar("OutputT")


class SqliteOrderExecution:
    """UoW y conexión compartidas; no es frontera autenticada ni autorizada.

    Exige políticas explícitas de transición y de línea. Las ofertas y pedidos
    usan la misma conexión y bloqueo. No protege escrituras que eludan la UoW.
    La entrega outbox requiere un worker independiente.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        dispatcher: DomainEventDispatcher,
        publisher: EventPublisher,
        transition_policy: OrderTransitionPolicy,
    ) -> None:
        self._connection = connection
        self._dispatcher = dispatcher
        self._publisher = publisher
        self._policy = transition_policy

    def _run(
        self,
        command: InputT,
        handler: UseCaseHandler[InputT, OutputT],
        uow: SqliteUnitOfWork,
        store: SqliteOrderIdempotencyStore,
    ) -> OutputT:
        # Exclusivo para estos handlers de pedidos: sus hooks solo gestionan idempotencia.
        class AtomicHandler:
            def handle(self, input: InputT, /) -> tuple[OutputT, Sequence[DomainEvent]]:
                outcome = handler.handle(input)
                if not isinstance(outcome, IdempotentReplay):
                    result, _ = outcome
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
                connection=self._connection, encoder=BusinessEventJsonCodec()
            ),
        )

    def create(self, command: CreateOrder) -> OrderDraftCreated:
        uow, store = (
            SqliteUnitOfWork(self._connection),
            SqliteOrderIdempotencyStore(self._connection),
        )
        handler = CreateOrderHandler(
            orders=SqliteOrderRepository(self._connection),
            locations=SqliteLocationRepository(self._connection),
            customers=SqliteCustomerRepository(self._connection),
            idempotency=store,
        )
        return self._run(command, handler, uow, store)

    def add_line(self, command: AddOrderLine, *, policy: OrderLinePolicy) -> OrderLineResult:
        if policy is None:
            raise ValueError("Se requiere política de línea")
        uow, store = (
            SqliteUnitOfWork(self._connection),
            SqliteOrderIdempotencyStore(self._connection),
        )
        handler = AddOrderLineHandler(
            orders=SqliteOrderRepository(self._connection),
            offerings=SqliteOfferingRepository(self._connection),
            guard=SqliteOrderMutationGuard(uow),
            policy=policy,
            idempotency=store,
        )
        return self._run(command, handler, uow, store)

    def remove_line(self, command: RemoveOrderLine) -> OrderLineRemoval:
        uow, store = (
            SqliteUnitOfWork(self._connection),
            SqliteOrderIdempotencyStore(self._connection),
        )
        handler = RemoveOrderLineHandler(
            orders=SqliteOrderRepository(self._connection),
            guard=SqliteOrderMutationGuard(uow),
            idempotency=store,
        )
        return self._run(command, handler, uow, store)

    def change_status(self, command: OrderStatusCommand) -> OrderStatusResult:
        handlers = {
            ValidateOrder: ValidateOrderHandler,
            ConfirmOrder: ConfirmOrderHandler,
            ReturnOrderToDraft: ReturnOrderToDraftHandler,
            CancelOrder: CancelOrderHandler,
            PrepareOrder: PrepareOrderHandler,
            MarkOrderReady: MarkOrderReadyHandler,
            DispatchOrder: DispatchOrderHandler,
            CompleteOrder: CompleteOrderHandler,
        }
        cls = handlers.get(type(command))
        if cls is None:
            raise ValueError("Comando de estado no soportado")
        uow, store = (
            SqliteUnitOfWork(self._connection),
            SqliteOrderIdempotencyStore(self._connection),
        )
        handler = cls(
            orders=SqliteOrderRepository(self._connection),
            guard=SqliteOrderMutationGuard(uow),
            policy=self._policy,
            idempotency=store,
        )
        return self._run(
            command,
            cast(UseCaseHandler[OrderStatusCommand, OrderStatusResult], handler),
            uow,
            store,
        )
