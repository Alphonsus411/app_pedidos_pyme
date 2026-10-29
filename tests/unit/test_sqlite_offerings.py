"""Pruebas del catálogo de ofertas SQLite."""

import sqlite3
from dataclasses import replace

import pytest

from universal_business.domain.catalog.entities import Offering
from universal_business.domain.catalog.value_objects import CatalogItemStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    OfferingId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money
from universal_business.infrastructure.sqlite_offerings import (
    SqliteOfferingRepository,
    create_sqlite_offerings_schema,
)
from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork


@pytest.fixture
def case(tmp_path):
    path = tmp_path / "offerings.db"
    connection = sqlite3.connect(path)
    create_sqlite_offerings_schema(connection)
    tenant, business, location = TenantId.generate(), BusinessId.generate(), LocationId.generate()
    item = Offering(
        id=OfferingId.generate(),
        tenant_id=tenant,
        business_id=business,
        name="Oferta",
        status=CatalogItemStatus.ACTIVE,
        base_price=Money("12.3456", "EUR"),
        metadata={"nested": ["a", 2]},
    )
    yield path, connection, SqliteOfferingRepository(connection), item, location
    connection.close()


def test_roundtrip_filters_scope_locations_and_status(case):
    path, connection, repo, item, location = case
    specific = replace(item, id=OfferingId.generate(), location_ids=frozenset({location}))
    other = replace(item, id=OfferingId.generate(), location_ids=frozenset({LocationId.generate()}))
    inactive = replace(item, id=OfferingId.generate(), status=CatalogItemStatus.INACTIVE)
    foreign = replace(item, id=OfferingId.generate(), tenant_id=TenantId.generate())
    with SqliteUnitOfWork(connection) as uow:
        for offering in (item, specific, other, inactive, foreign):
            repo.save(offering)
        uow.commit()
    with sqlite3.connect(path) as reader:
        persisted = SqliteOfferingRepository(reader).get(
            tenant_id=item.tenant_id, business_id=item.business_id, offering_id=item.id
        )
        assert persisted.base_price == Money("12.3456", "EUR")
        assert persisted.metadata == {"nested": ["a", 2]}
        assert persisted.domain_events == []
        assert (
            SqliteOfferingRepository(reader).get(
                tenant_id=item.tenant_id, business_id=BusinessId.generate(), offering_id=item.id
            )
            is None
        )
    assert {
        x.id
        for x in repo.list_active(
            tenant_id=item.tenant_id, business_id=item.business_id, location_id=location
        )
    } == {item.id, specific.id}
    assert len(repo.list_by_business(tenant_id=item.tenant_id, business_id=item.business_id)) == 4


def test_transaction_rollback_and_scope_immutability(case):
    _, connection, repo, item, _ = case
    with pytest.raises(RuntimeError, match="transacción"):
        repo.save(item)
    with SqliteUnitOfWork(connection):
        repo.save(item)
    assert (
        repo.get(tenant_id=item.tenant_id, business_id=item.business_id, offering_id=item.id)
        is None
    )
    with SqliteUnitOfWork(connection) as uow:
        repo.save(item)
        uow.commit()
    with SqliteUnitOfWork(connection):
        with pytest.raises(ValueError, match="negocio"):
            repo.save(replace(item, business_id=BusinessId.generate()))
    assert (
        repo.get(tenant_id=item.tenant_id, business_id=item.business_id, offering_id=item.id)
        is not None
    )


def test_unsupported_metadata_and_corruption_fail_closed(case):
    _, connection, repo, item, _ = case
    with SqliteUnitOfWork(connection):
        with pytest.raises(ValueError, match="metadata"):
            repo.save(replace(item, metadata={"float": 0.1}))
    with SqliteUnitOfWork(connection) as uow:
        repo.save(item)
        connection.execute(
            "UPDATE offerings SET payload=?",
            ('{"version":true,"locations":[],"metadata":{},"price":null}',),
        )
        uow.commit()
    with pytest.raises(ValueError, match="inválida"):
        repo.get(tenant_id=item.tenant_id, business_id=item.business_id, offering_id=item.id)


def test_concurrent_writer_blocked_until_transaction_ends(case):
    path, connection, repo, item, _ = case
    with SqliteUnitOfWork(connection) as uow:
        repo.save(item)
        uow.commit()
    with sqlite3.connect(path, timeout=0) as second:
        with SqliteUnitOfWork(connection):
            assert (
                repo.get(
                    tenant_id=item.tenant_id, business_id=item.business_id, offering_id=item.id
                )
                is not None
            )
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                with SqliteUnitOfWork(second):
                    pass
        with SqliteUnitOfWork(second) as uow:
            uow.commit()


def test_add_line_uses_persisted_offering_under_shared_transaction(tmp_path):
    from decimal import Decimal
    from unittest.mock import Mock
    from uuid import uuid4

    from universal_business.application.events.business_event_codec import BusinessEventJsonCodec
    from universal_business.application.idempotency import IdempotencyKey, scoped_idempotency_key
    from universal_business.application.orders.add_line import AddOrderLineHandler
    from universal_business.application.orders.commands import AddOrderLine
    from universal_business.application.request_digest import request_digest
    from universal_business.domain.orders.entities import Order
    from universal_business.domain.orders.value_objects import OrderChannel, OrderStatus
    from universal_business.domain.shared.value_objects.ids import OrderId
    from universal_business.infrastructure.sqlite_idempotency import (
        create_sqlite_idempotency_schema,
    )
    from universal_business.infrastructure.sqlite_order_idempotency import (
        SqliteOrderIdempotencyStore,
    )
    from universal_business.infrastructure.sqlite_orders import (
        SqliteOrderMutationGuard,
        SqliteOrderRepository,
        create_sqlite_orders_schema,
    )
    from universal_business.infrastructure.sqlite_outbox import (
        SqliteOutboxWriter,
        create_sqlite_outbox_schema,
    )

    path = tmp_path / "order.db"
    tid, bid, lid = TenantId.generate(), BusinessId.generate(), LocationId.generate()
    offering = Offering(
        id=OfferingId.generate(),
        tenant_id=tid,
        business_id=bid,
        name="Producto",
        status=CatalogItemStatus.ACTIVE,
        base_price=Money("12", "EUR"),
        location_ids=frozenset({lid}),
    )
    order = Order(
        id=OrderId.generate(),
        tenant_id=tid,
        business_id=bid,
        location_id=lid,
        status=OrderStatus.DRAFT,
        channel=OrderChannel.WEB,
    )
    cmd = AddOrderLine(
        tenant_id=tid,
        business_id=bid,
        location_id=lid,
        order_id=order.id,
        offering_id=offering.id,
        line_id=uuid4(),
        quantity=Decimal("2"),
        discount=Money("0", "EUR"),
        tax=Money("0", "EUR"),
        idempotency_key=IdempotencyKey(value="add-offering-001"),
    )
    with sqlite3.connect(path) as connection:
        for schema in (
            create_sqlite_offerings_schema,
            create_sqlite_orders_schema,
            create_sqlite_outbox_schema,
            create_sqlite_idempotency_schema,
        ):
            schema(connection)
        with SqliteUnitOfWork(connection) as uow:
            SqliteOfferingRepository(connection).save(offering)
            SqliteOrderRepository(connection).save(order)
            uow.commit()
        with SqliteUnitOfWork(connection) as uow:
            store = SqliteOrderIdempotencyStore(connection)
            policy = Mock()
            policy.approve.return_value = True
            handler = AddOrderLineHandler(
                orders=SqliteOrderRepository(connection),
                offerings=SqliteOfferingRepository(connection),
                guard=SqliteOrderMutationGuard(uow),
                policy=policy,
                idempotency=store,
            )
            result, events = handler.handle(cmd)
            key = scoped_idempotency_key(
                business_id=bid,
                operation=f"{type(cmd).__module__}.{type(cmd).__qualname__}",
                key=cmd.idempotency_key,
            )
            store.complete_in_uow(uow, tid, key, request_digest(cmd), result)
            SqliteOutboxWriter(connection=connection, encoder=BusinessEventJsonCodec()).write_many(
                events
            )
            uow.commit()
    with sqlite3.connect(path) as reader:
        saved = SqliteOrderRepository(reader).get(tenant_id=tid, order_id=order.id)
        assert saved.total == Money("24", "EUR")
        assert saved.lines[0].offering_id == offering.id
        assert reader.execute("SELECT count(*) FROM transactional_outbox").fetchone() == (1,)
        assert reader.execute("SELECT state FROM idempotency").fetchone() == ("done",)
