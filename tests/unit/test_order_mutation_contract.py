"""Un fake demuestra el uso esperado, no el aislamiento de una base real."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from threading import Event, Lock
from uuid import uuid4

from universal_business.domain.orders.entities import Order
from universal_business.domain.orders.line import OrderLine
from universal_business.domain.orders.mutation import OrderMutationGuard
from universal_business.domain.orders.value_objects import OrderChannel, OrderStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    OfferingId,
    OrderId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money


def test_serialized_edits_do_not_lose_lines() -> None:
    order = Order(
        id=OrderId.generate(),
        tenant_id=TenantId.generate(),
        business_id=BusinessId.generate(),
        location_id=LocationId.generate(),
        status=OrderStatus.DRAFT,
        channel=OrderChannel.WEB,
    )
    lock, first_locked, second_attempt = Lock(), Event(), Event()
    state = [order]

    class FakeTransaction:
        def protect(
            self,
            *,
            tenant_id: TenantId,
            business_id: BusinessId,
            location_id: LocationId,
            order_id: OrderId,
        ) -> None:
            assert (tenant_id, business_id, location_id, order_id) == (
                order.tenant_id,
                order.business_id,
                order.location_id,
                order.id,
            )
            lock.acquire()

    def edit(first: bool) -> None:
        guard: OrderMutationGuard = FakeTransaction()
        if not first:
            assert first_locked.wait(2)
            second_attempt.set()
        guard.protect(
            tenant_id=order.tenant_id,
            business_id=order.business_id,
            location_id=order.location_id,
            order_id=order.id,
        )
        try:
            if first:
                first_locked.set()
                assert second_attempt.wait(2)
            current = replace(state[0])
            current.add_line(
                OrderLine(
                    line_id=uuid4(),
                    offering_id=OfferingId.generate(),
                    name="Producto",
                    quantity=Decimal(1),
                    unit_price=Money(10, "EUR"),
                    discount=Money(0, "EUR"),
                    tax=Money(0, "EUR"),
                )
            )
            state[0] = current  # Commit simulado mientras el lock sigue adquirido.
        finally:
            lock.release()

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(edit, True), pool.submit(edit, False)
        a.result(timeout=5)
        b.result(timeout=5)
    assert len(state[0].lines) == 2
    assert state[0].total == Money(20, "EUR")
