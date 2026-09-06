"""Tests unitarios para Customer, ContactPoint, Consent."""

from __future__ import annotations

import datetime as dt

import pytest

from universal_business.domain.business.value_objects import Address as CAddress
from universal_business.domain.customers.entities import Customer
from universal_business.domain.customers.value_objects import (
    Consent,
    ContactPoint,
    CustomerStatus,
)
from universal_business.domain.shared.errors import (
    InvariantViolationError,
    TimezoneAwareRequiredError,
)
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CustomerId,
    LocationId,
    TenantId,
)
from universal_business.domain.shared.value_objects.temporal import UTC


def _base_kw(location_id=None):
    result = dict(
        id=CustomerId.generate(),
        tenant_id=TenantId.generate(),
        business_id=BusinessId.generate(),
        given_name="Ada",
        contact_points=[ContactPoint(kind="EMAIL", value="ada@lovelace.io", is_primary=True)],
    )
    if location_id is not None:
        result["location_id"] = location_id
    return result


def test_customer_basics() -> None:
    c = Customer(**_base_kw())
    assert c.full_name == "Ada"
    assert c.status == CustomerStatus.DRAFT


def test_customer_location_id_is_optional() -> None:
    loc = LocationId.generate()
    c_with = Customer(**_base_kw(location_id=loc))
    c_wo = Customer(**_base_kw(location_id=None))
    assert c_with.location_id == loc
    assert c_wo.location_id is None
    # La identidad (id) NO depende de location_id — misma id sin location_id
    cid = CustomerId.generate()
    kw1 = _base_kw()
    kw1["id"] = cid
    kw1["location_id"] = None
    kw2 = dict(kw1)
    kw2["location_id"] = loc
    assert Customer(**kw1).id == Customer(**kw2).id  # misma identidad


def test_customer_requires_tenant_and_business() -> None:
    kw = _base_kw()
    del kw["tenant_id"]
    with pytest.raises(TypeError):
        Customer(**kw)
    kw = _base_kw()
    del kw["business_id"]
    with pytest.raises(TypeError):
        Customer(**kw)


def test_customer_empty_given_name_rejected() -> None:
    kw = _base_kw()
    kw["given_name"] = "   "
    with pytest.raises(InvariantViolationError):
        Customer(**kw)


def test_contact_point_invalid_kind() -> None:
    with pytest.raises(InvariantViolationError):
        ContactPoint(kind="CARRIER_PIGEON", value="xyz")  # type: ignore[arg-type]


def test_contact_point_email_format() -> None:
    with pytest.raises(InvariantViolationError):
        ContactPoint(kind="EMAIL", value="not-an-email")


def test_contact_point_verified_at_must_be_aware() -> None:
    with pytest.raises(TimezoneAwareRequiredError):
        ContactPoint(
            kind="EMAIL",
            value="a@b.co",
            verified_at=dt.datetime(2025, 1, 1),  # naive
        )


def test_consent_revoked_after_granted() -> None:
    t1 = dt.datetime(2025, 1, 1, 10, 0, tzinfo=UTC)
    t0 = t1 - dt.timedelta(days=1)
    # revoked < granted → KO
    with pytest.raises(InvariantViolationError):
        Consent(
            kind="TERMS_AND_CONDITIONS",
            source="app-v1",
            granted_at=t1,
            revoked_at=t0,
        )
    Consent(kind="TERMS_AND_CONDITIONS", source="app", granted_at=t1)


def test_customer_active_requires_contact_point() -> None:
    c = Customer(
        id=CustomerId.generate(),
        tenant_id=TenantId.generate(),
        business_id=BusinessId.generate(),
        given_name="X",
        contact_points=[],
        status=CustomerStatus.DRAFT,
    )
    # No puede ir a ACTIVE sin contact points
    with pytest.raises(InvariantViolationError):
        c.transition_to(CustomerStatus.ACTIVE)
    cp = ContactPoint(kind="PHONE", value="+18005550100")
    c.add_contact_point(cp)
    c.transition_to(CustomerStatus.ACTIVE)
    assert c.status == CustomerStatus.ACTIVE


def test_customer_add_address_and_consent() -> None:
    c = Customer(**_base_kw())
    a = CAddress(country_code="US")
    c.add_address(a)
    assert len(c.addresses) == 1
    con = Consent(kind="MARKETING", source="web", granted_at=dt.datetime.now(UTC))
    c.record_consent(con)
    assert len(c.consents) == 1
    assert con.is_active


def test_customer_primary_contact_promoted() -> None:
    kw = _base_kw()
    kw["contact_points"] = [ContactPoint(kind="EMAIL", value="old@x.co", is_primary=True)]
    c = Customer(**kw)
    new_primary = ContactPoint(kind="EMAIL", value="new@x.co", is_primary=True)
    c.add_contact_point(new_primary)
    assert c.primary_contact is not None
    assert c.primary_contact.value == "new@x.co"
    # El anterior ya no es primary
    primaries = [cp for cp in c.contact_points if cp.is_primary]
    assert len(primaries) == 1
