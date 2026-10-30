"""Demostración local con datos ficticios y publicación simulada."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from universal_business.application.events.business_event_codec import BusinessEventJsonCodec
from universal_business.application.events.dispatcher import DomainEventDispatcher
from universal_business.application.events.outbox_delivery import OutboxDeliveryWorker
from universal_business.application.idempotency import IdempotencyKey
from universal_business.application.orders.commands import (
    AddOrderLine,
    ConfirmOrder,
    CreateOrder,
    ValidateOrder,
)
from universal_business.application.reservations.commands import (
    ConfirmReservation,
    CreateReservation,
)
from universal_business.domain.availability.entities import AvailabilityRule
from universal_business.domain.business.entities import Location
from universal_business.domain.business.value_objects import Address, LocationStatus, OperatingHours
from universal_business.domain.catalog.entities import Offering
from universal_business.domain.catalog.value_objects import CatalogItemStatus
from universal_business.domain.customers.entities import Customer
from universal_business.domain.orders.value_objects import OrderChannel, OrderStatus
from universal_business.domain.reservations.interval import ReservationInterval
from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.resources.entities import Resource
from universal_business.domain.shared.value_objects.ids import (
    AvailabilityRuleId,
    BusinessId,
    CustomerId,
    LocationId,
    OfferingId,
    OrderId,
    ReservationId,
    ResourceId,
    ResourceTypeId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money
from universal_business.domain.shared.value_objects.temporal import DateRange, TimeRange
from universal_business.infrastructure.sqlite_availability import SqliteAvailabilityRepository
from universal_business.infrastructure.sqlite_customers import SqliteCustomerRepository
from universal_business.infrastructure.sqlite_locations import SqliteLocationRepository
from universal_business.infrastructure.sqlite_offerings import SqliteOfferingRepository
from universal_business.infrastructure.sqlite_order_execution import SqliteOrderExecution
from universal_business.infrastructure.sqlite_orders import SqliteOrderRepository
from universal_business.infrastructure.sqlite_outbox import SqliteOutboxDeliveryStore
from universal_business.infrastructure.sqlite_reservation_execution import (
    SqliteReservationExecution,
)
from universal_business.infrastructure.sqlite_reservations import SqliteReservationRepository
from universal_business.infrastructure.sqlite_resources import SqliteResourceRepository
from universal_business.infrastructure.sqlite_schema import initialize_sqlite_schema
from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork


class DemoTransitionPolicy:
    """Ejemplo limitado a validar y confirmar un pedido de demostración."""

    def approve(self, *, order, target):
        return (order.status, target) in {
            (OrderStatus.DRAFT, OrderStatus.VALIDATED),
            (OrderStatus.VALIDATED, OrderStatus.CONFIRMED),
        }


class DemoLinePolicy:
    """Ejemplo sin descuentos ni impuestos; no es una política fiscal."""

    def approve(self, *, order, offering, line):
        return (
            order.status == OrderStatus.DRAFT
            and offering.status == CatalogItemStatus.ACTIVE
            and line.discount.amount == 0
            and line.tax.amount == 0
        )


class DemoPublisher:
    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)

    def publish_many(self, events):
        self.events.extend(events)


def run_demo(tmp_path, *, location_name="Local", product_name="Producto", product_price="10"):
    path = tmp_path / "prototype.db"
    tenant, business, location = TenantId.generate(), BusinessId.generate(), LocationId.generate()
    customer, resource, offering = (
        CustomerId.generate(),
        ResourceId.generate(),
        OfferingId.generate(),
    )
    order, reservation = OrderId.generate(), ReservationId.generate()
    start = datetime(2026, 11, 5, 10, tzinfo=UTC)
    with closing(sqlite3.connect(path)) as connection:
        initialize_sqlite_schema(connection)
        with SqliteUnitOfWork(connection) as uow:
            SqliteLocationRepository(connection).save(
                Location(
                    id=location,
                    tenant_id=tenant,
                    business_id=business,
                    name=location_name,
                    address=Address(country_code="ES"),
                    timezone="UTC",
                    operating_hours=OperatingHours(),
                    status=LocationStatus.OPEN,
                )
            )
            SqliteCustomerRepository(connection).save(
                Customer(id=customer, tenant_id=tenant, business_id=business, given_name="Cliente")
            )
            SqliteResourceRepository(connection).save(
                Resource(
                    id=resource,
                    tenant_id=tenant,
                    business_id=business,
                    location_id=location,
                    resource_type_id=ResourceTypeId.generate(),
                    name="Mesa",
                    capacity=4,
                )
            )
            SqliteAvailabilityRepository(connection).save_rule(
                AvailabilityRule(
                    id=AvailabilityRuleId.generate(),
                    tenant_id=tenant,
                    location_id=location,
                    effective_range=DateRange.single(start.date()),
                    time_ranges=[TimeRange(start, start + timedelta(hours=3))],
                )
            )
            SqliteOfferingRepository(connection).save(
                Offering(
                    id=offering,
                    tenant_id=tenant,
                    business_id=business,
                    name=product_name,
                    status=CatalogItemStatus.ACTIVE,
                    base_price=Money(product_price, "EUR"),
                )
            )
            uow.commit()
        transition, line_policy = DemoTransitionPolicy(), DemoLinePolicy()
        orders = SqliteOrderExecution(
            connection,
            dispatcher=DomainEventDispatcher(),
            publisher=DemoPublisher(),
            transition_policy=transition,
        )
        reservations = SqliteReservationExecution(
            connection, dispatcher=DomainEventDispatcher(), publisher=DemoPublisher()
        )
        scope = dict(tenant_id=tenant, business_id=business, location_id=location)
        create_order = CreateOrder(
            **scope,
            order_id=order,
            channel=OrderChannel.WEB,
            customer_id=customer,
            idempotency_key=IdempotencyKey(value="prototype-order-create"),
        )
        orders.create(create_order)
        add = AddOrderLine(
            **scope,
            order_id=order,
            offering_id=offering,
            line_id=uuid4(),
            quantity=Decimal("2"),
            discount=Money("0", "EUR"),
            tax=Money("0", "EUR"),
            idempotency_key=IdempotencyKey(value="prototype-order-line"),
        )
        orders.add_line(add, policy=line_policy)
        for cls, name in ((ValidateOrder, "validate"), (ConfirmOrder, "confirm")):
            orders.change_status(
                cls(
                    **scope,
                    order_id=order,
                    idempotency_key=IdempotencyKey(value=f"prototype-order-{name}"),
                )
            )
        create_reservation = CreateReservation(
            **scope,
            resource_id=resource,
            customer_id=customer,
            reservation_id=reservation,
            interval=ReservationInterval(start, start + timedelta(hours=1)),
            party_size=2,
            idempotency_key=IdempotencyKey(value="prototype-res-create"),
        )
        reservations.create(create_reservation)
        confirm = ConfirmReservation(
            **scope,
            reservation_id=reservation,
            idempotency_key=IdempotencyKey(value="prototype-res-confirm"),
        )
        reservations.confirm(confirm)
        assert orders.create(create_order).order_id == order
        assert reservations.confirm(confirm).reservation_id == reservation
        assert connection.execute("SELECT count(*) FROM transactional_outbox").fetchone() == (6,)
    with closing(sqlite3.connect(path)) as connection:
        initialize_sqlite_schema(connection)
        assert (
            SqliteOrderRepository(connection).get(tenant_id=tenant, order_id=order).status
            == OrderStatus.CONFIRMED
        )
        assert (
            SqliteReservationRepository(connection)
            .get(tenant_id=tenant, reservation_id=reservation)
            .status
            == ReservationStatus.CONFIRMED
        )
    publisher = DemoPublisher()
    store = SqliteOutboxDeliveryStore(
        connect=lambda: sqlite3.connect(path), decoder=BusinessEventJsonCodec(), lease_seconds=60
    )
    worker = OutboxDeliveryWorker(store=store, publisher=publisher)
    while worker.process_one():
        pass
    print(f"Pedido: {OrderStatus.CONFIRMED.value}")
    print(f"Reserva: {ReservationStatus.CONFIRMED.value}")
    print(f"Eventos procesados en simulación: {len(publisher.events)}")


if __name__ == "__main__":
    with TemporaryDirectory(prefix="pedidos-demo-") as temporary:
        run_demo(Path(temporary))
