"""La demostración se puede ejecutar en un proceso limpio."""

import os
import subprocess
import sys
from pathlib import Path


def test_demo_runs_with_ephemeral_database(tmp_path):
    root = Path(__file__).resolve().parents[2]
    env = dict(
        os.environ,
        PYTHONPATH=str(root / "src"),
        TMPDIR=str(tmp_path),
        TEMP=str(tmp_path),
        TMP=str(tmp_path),
    )
    run = subprocess.run(
        [sys.executable, str(root / "examples" / "sqlite_demo.py")],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert "Pedido: confirmed" in run.stdout
    assert "Reserva: confirmed" in run.stdout
    assert "Eventos procesados en simulación: 6" in run.stdout
    assert list(tmp_path.iterdir()) == []


def test_demo_policies_reject_out_of_scope_actions():
    import runpy
    from dataclasses import replace
    from decimal import Decimal
    from uuid import uuid4

    from universal_business.domain.catalog.entities import Offering
    from universal_business.domain.catalog.value_objects import CatalogItemStatus
    from universal_business.domain.orders.entities import Order
    from universal_business.domain.orders.line import OrderLine
    from universal_business.domain.orders.value_objects import OrderChannel, OrderStatus
    from universal_business.domain.shared.value_objects.ids import (
        BusinessId,
        LocationId,
        OfferingId,
        OrderId,
        TenantId,
    )
    from universal_business.domain.shared.value_objects.money import Money

    namespace = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "examples" / "sqlite_demo.py")
    )
    transition, line_policy = namespace["DemoTransitionPolicy"](), namespace["DemoLinePolicy"]()
    tenant, business = TenantId.generate(), BusinessId.generate()
    order = Order(
        id=OrderId.generate(),
        tenant_id=tenant,
        business_id=business,
        location_id=LocationId.generate(),
        status=OrderStatus.DRAFT,
        channel=OrderChannel.WEB,
    )
    offering = Offering(
        id=OfferingId.generate(),
        tenant_id=tenant,
        business_id=business,
        name="Demo",
        status=CatalogItemStatus.ACTIVE,
        base_price=Money("10", "EUR"),
    )
    line = OrderLine(
        line_id=uuid4(),
        offering_id=offering.id,
        name="Demo",
        quantity=Decimal("1"),
        unit_price=Money("10", "EUR"),
        discount=Money("0", "EUR"),
        tax=Money("0", "EUR"),
    )
    assert transition.approve(order=order, target=OrderStatus.VALIDATED)
    assert not transition.approve(order=order, target=OrderStatus.CONFIRMED)
    assert line_policy.approve(order=order, offering=offering, line=line)
    assert not line_policy.approve(
        order=order, offering=offering, line=replace(line, discount=Money("1", "EUR"))
    )
    assert not line_policy.approve(
        order=order, offering=offering, line=replace(line, tax=Money("1", "EUR"))
    )
    assert not line_policy.approve(
        order=order, offering=replace(offering, status=CatalogItemStatus.INACTIVE), line=line
    )
