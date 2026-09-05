"""Tests unitarios para módulo business (Tenant / Business / Location + VOs)."""

from __future__ import annotations

import datetime as dt

import pytest

from universal_business.domain.business.entities import Business, Location, Tenant
from universal_business.domain.business.value_objects import (
    WEEKDAYS,
    Address,
    BusinessSettings,
    BusinessStatus,
    ContactInfo,
    LocationStatus,
    OperatingHours,
    TenantStatus,
)
from universal_business.domain.shared.errors import (
    InvariantViolationError,
    MoneyCurrencyMismatchError,
    StatusTransitionError,
    TenantBoundaryViolationError,
)
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    TenantId,
)
from universal_business.domain.shared.value_objects.temporal import TimeRange


def _fresh_tenant(**kw):
    return Tenant(
        id=TenantId.generate(),
        display_name="Demo Tenant",
        status=TenantStatus.PENDING_ONBOARDING,
        **kw,
    )


def _fresh_business(tenant_id: TenantId | None = None, **kw):
    tid = tenant_id or TenantId.generate()
    return Business(
        id=BusinessId.generate(),
        tenant_id=tid,
        name="Biz",
        contact_info=ContactInfo(email="a@b.co"),
        settings=BusinessSettings(default_currency="USD"),
        status=BusinessStatus.DRAFT,
        **kw,
    )


def _fresh_location(business: Business, **kw):
    defaults = dict(
        id=LocationId.generate(),
        tenant_id=business.tenant_id,
        business_id=business.id,
        name="Store One",
        address=Address(country_code="DO", city="SDQ"),
        timezone="America/Santo_Domingo",
        operating_hours=OperatingHours(),
        status=LocationStatus.DRAFT,
    )
    defaults.update(kw)
    return Location(**defaults)


# ---------------------------------------------------------------------------
# Address
# ---------------------------------------------------------------------------
def test_address_invalid_country_code() -> None:
    with pytest.raises(InvariantViolationError):
        Address(country_code="dom")  # lowercase + >2


def test_address_normalizes_country_to_uppercase() -> None:
    a = Address(country_code="us")
    assert a.country_code == "US"


# ---------------------------------------------------------------------------
# ContactInfo
# ---------------------------------------------------------------------------
def test_contact_info_requires_at_least_one() -> None:
    with pytest.raises(InvariantViolationError):
        ContactInfo()


def test_contact_info_email_format() -> None:
    with pytest.raises(InvariantViolationError):
        ContactInfo(email="not-an-email")


# ---------------------------------------------------------------------------
# BusinessSettings
# ---------------------------------------------------------------------------
def test_business_settings_invalid_currency() -> None:
    with pytest.raises(MoneyCurrencyMismatchError):
        BusinessSettings(default_currency="BTC")


# ---------------------------------------------------------------------------
# Tenant
# ---------------------------------------------------------------------------
def test_tenant_requires_display_name() -> None:
    with pytest.raises(InvariantViolationError):
        Tenant(id=TenantId.generate(), display_name="")


def test_tenant_legal_tax_id_requires_name() -> None:
    with pytest.raises(InvariantViolationError):
        _fresh_tenant(legal_entity_name=None, legal_tax_id="123")


def test_tenant_legal_entity_is_optional() -> None:
    t = _fresh_tenant(legal_entity_name=None, legal_tax_id=None)
    assert not t.is_legal_entity
    t2 = _fresh_tenant(legal_entity_name="ACME Inc", legal_tax_id="1234")
    assert t2.is_legal_entity


def test_tenant_fsm_transitions() -> None:
    t = _fresh_tenant()
    # Pendiente no puede ir a suspendido
    with pytest.raises(StatusTransitionError):
        t.transition_to(TenantStatus.SUSPENDED)
    t.transition_to(TenantStatus.ACTIVE)
    assert t.status == TenantStatus.ACTIVE


# ---------------------------------------------------------------------------
# Business
# ---------------------------------------------------------------------------
def test_business_requires_contact_info() -> None:
    with pytest.raises(InvariantViolationError):
        Business(
            id=BusinessId.generate(),
            tenant_id=TenantId.generate(),
            name="X",
            contact_info=None,  # type: ignore[arg-type]
            settings=BusinessSettings(default_currency="DOP"),
        )


def test_business_fsm() -> None:
    b = _fresh_business()
    b.transition_to(BusinessStatus.OPERATIONAL)
    assert b.status == BusinessStatus.OPERATIONAL
    # OPERATIONAL no puede ir a DRAFT
    with pytest.raises(StatusTransitionError):
        b.transition_to(BusinessStatus.DRAFT)


# ---------------------------------------------------------------------------
# Location + OperatingHours
# ---------------------------------------------------------------------------
def test_location_invalid_timezone() -> None:
    biz = _fresh_business()
    with pytest.raises(InvariantViolationError):
        _fresh_location(biz, timezone="NotATimezone")  # sin "/" ni igual a "UTC"


def test_operating_hours_7_days_by_default_empty() -> None:
    oh = OperatingHours()
    for day in WEEKDAYS:
        assert oh.is_closed(day)


def test_operating_hours_covers_checks_tz() -> None:
    tz_arg = dt.timezone(dt.timedelta(hours=-4), name="AST")
    slot = TimeRange(
        dt.datetime(2025, 6, 1, 9, 0, tzinfo=tz_arg),
        dt.datetime(2025, 6, 1, 18, 0, tzinfo=tz_arg),
    )
    oh = OperatingHours(by_day={"SUNDAY": [slot]})  # 2025-06-01 es DOMINGO
    inside = dt.datetime(2025, 6, 1, 12, 0, tzinfo=tz_arg)
    assert oh.covers(inside)
    outside = dt.datetime(2025, 6, 1, 7, 0, tzinfo=tz_arg)
    assert not oh.covers(outside)


def test_location_assert_tenancy_consistency() -> None:
    biz1 = _fresh_business()
    biz2 = _fresh_business()
    loc1 = _fresh_location(biz1)
    # OK
    loc1.assert_tenancy_consistency(biz1)
    # KO - business mismatch
    with pytest.raises(InvariantViolationError):
        loc1.assert_tenancy_consistency(biz2)
    # KO - tenant_id falso (forzado)
    bad_loc = Location(
        id=LocationId.generate(),
        tenant_id=biz2.tenant_id,  # distinto del de biz1
        business_id=biz1.id,
        name="Bad",
        address=Address(country_code="DO"),
        timezone="America/Santo_Domingo",
        operating_hours=OperatingHours(),
    )
    with pytest.raises(TenantBoundaryViolationError):
        bad_loc.assert_tenancy_consistency(biz1)
