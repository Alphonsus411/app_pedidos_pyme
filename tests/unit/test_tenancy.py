"""Tests de invariantes de tenancy y aislamiento conceptual."""

from __future__ import annotations

import datetime as dt

import pytest

from universal_business.domain.business.entities import Business, Location, Tenant
from universal_business.domain.business.value_objects import (
    Address,
    BusinessSettings,
    BusinessStatus,
    ContactInfo,
    LocationStatus,
    OperatingHours,
    TenantStatus,
)
from universal_business.domain.catalog.entities import CatalogItem
from universal_business.domain.catalog.value_objects import CatalogItemStatus, CatalogItemType
from universal_business.domain.customers.entities import Customer
from universal_business.domain.customers.value_objects import ContactPoint, CustomerStatus
from universal_business.domain.orders.entities import Order
from universal_business.domain.orders.value_objects import OrderChannel, OrderStatus
from universal_business.domain.reservations.entities import Reservation
from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.resources.entities import Resource
from universal_business.domain.resources.value_objects import ResourceStatus
from universal_business.domain.shared.errors import (
    TenantBoundaryViolationError,
)
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CatalogItemId,
    CustomerId,
    LocationId,
    OrderId,
    ReservationId,
    ResourceId,
    ResourceTypeId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money
from universal_business.domain.shared.value_objects.temporal import UTC, TimeRange


def build_stack():
    t = Tenant(id=TenantId.generate(), display_name="Tenant A", status=TenantStatus.ACTIVE)
    b = Business(
        id=BusinessId.generate(),
        tenant_id=t.id,
        name="Biz A1",
        contact_info=ContactInfo(email="a@b.co"),
        settings=BusinessSettings(default_currency="DOP"),
        status=BusinessStatus.OPERATIONAL,
    )
    loc = Location(
        id=LocationId.generate(),
        tenant_id=t.id,
        business_id=b.id,
        name="Loc 1",
        address=Address(country_code="DO"),
        timezone="America/Santo_Domingo",
        operating_hours=OperatingHours(),
        status=LocationStatus.OPEN,
    )
    return t, b, loc


def test_location_tenant_id_redundant_matches_business() -> None:
    """Invariante de tenancy: Location.tenant_id conceptualmente == su Business.tenant_id."""
    _, b, loc = build_stack()
    assert loc.tenant_id == b.tenant_id
    loc.assert_tenancy_consistency(b)


def test_cross_tenant_location_mismatch_detected() -> None:
    _, b1, _ = build_stack()
    # Crear un tenant 2 y un business 2
    t2 = Tenant(id=TenantId.generate(), display_name="Tenant B", status=TenantStatus.ACTIVE)
    b2 = Business(
        id=BusinessId.generate(),
        tenant_id=t2.id,
        name="Biz B",
        contact_info=ContactInfo(email="b@b.co"),
        settings=BusinessSettings(default_currency="USD"),
    )
    # Una Location con tenant_id de T1 pero business_id de b2 → assert_tenancy detecta
    loc_tainted = Location(
        id=LocationId.generate(),
        tenant_id=b1.tenant_id,
        business_id=b2.id,
        name="Bogus",
        address=Address(country_code="US"),
        timezone="UTC",
        operating_hours=OperatingHours(),
    )
    with pytest.raises(TenantBoundaryViolationError):
        loc_tainted.assert_tenancy_consistency(b2)


def test_resource_location_id_provided_ok_uses_new_resource_type_entity() -> None:
    t, b, loc = build_stack()
    rtid = ResourceTypeId.generate()
    r = Resource(
        id=ResourceId.generate(),
        tenant_id=t.id,
        business_id=b.id,
        location_id=loc.id,
        name="Mesa 1",
        resource_type_id=rtid,
        status=ResourceStatus.ACTIVE,
    )
    assert r.location_id == loc.id
    assert r.resource_type_id == rtid


def test_order_location_id_and_tenancy() -> None:
    t, b, loc = build_stack()
    c = Customer(
        id=CustomerId.generate(),
        tenant_id=t.id,
        business_id=b.id,
        given_name="Juana",
        contact_points=[ContactPoint(kind="EMAIL", value="j@x.co")],
        status=CustomerStatus.ACTIVE,
    )
    o = Order(
        id=OrderId.generate(),
        tenant_id=t.id,
        business_id=b.id,
        location_id=loc.id,
        status=OrderStatus.DRAFT,
        channel=OrderChannel.COUNTER,
        total=Money("1500.00", "DOP"),
        customer_id=c.id,
    )
    assert o.tenant_id == t.id
    assert o.location_id == loc.id


def test_catalog_item_location_optional_allows_business_level() -> None:
    t, b, loc = build_stack()
    # Catálogo a nivel business (sin location)
    item_global = CatalogItem(
        id=CatalogItemId.generate(),
        tenant_id=t.id,
        business_id=b.id,
        name="Producto general",
        type=CatalogItemType.PRODUCT,
        status=CatalogItemStatus.ACTIVE,
        location_id=None,
    )
    # Específico por location
    item_local = CatalogItem(
        id=CatalogItemId.generate(),
        tenant_id=t.id,
        business_id=b.id,
        name="Producto local",
        type=CatalogItemType.PRODUCT,
        status=CatalogItemStatus.ACTIVE,
        location_id=loc.id,
    )
    assert item_global.location_id is None
    assert item_local.location_id == loc.id


def test_reservation_requires_location_and_tenancy() -> None:
    t, b, loc = build_stack()
    rtid = ResourceTypeId.generate()
    r = Resource(
        id=ResourceId.generate(),
        tenant_id=t.id,
        business_id=b.id,
        location_id=loc.id,
        name="Table 5",
        resource_type_id=rtid,
    )
    cid = CustomerId.generate()
    now = dt.datetime.now(UTC)
    tr = TimeRange(now, now + dt.timedelta(hours=1))
    rv = Reservation(
        id=ReservationId.generate(),
        tenant_id=t.id,
        business_id=b.id,
        location_id=loc.id,
        customer_id=cid,
        resource_id=r.id,
        time_range=tr,
        status=ReservationStatus.CONFIRMED,
    )
    assert rv.location_id == loc.id
    assert rv.tenant_id == t.id
