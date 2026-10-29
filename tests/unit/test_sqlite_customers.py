"""Persistencia de clientes con SQLite real y alcance explícito."""

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from universal_business.domain.business.value_objects import Address
from universal_business.domain.customers.entities import Customer
from universal_business.domain.customers.value_objects import (
    Consent,
    ContactPoint,
    CustomerPreferences,
    CustomerStatus,
)
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CustomerId,
    LocationId,
    TenantId,
)
from universal_business.infrastructure.sqlite_customers import (
    SqliteCustomerRepository,
    create_sqlite_customers_schema,
)
from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "customers.db"
    with sqlite3.connect(path) as connection:
        create_sqlite_customers_schema(connection)
    return path


@pytest.fixture
def customer() -> Customer:
    now = datetime(2026, 10, 29, 10, tzinfo=UTC)
    return Customer(
        id=CustomerId.generate(),
        tenant_id=TenantId.generate(),
        business_id=BusinessId.generate(),
        given_name="Ada",
        family_name="Lovelace",
        external_ref="reference-1",
        status=CustomerStatus.ACTIVE,
        contact_points=[ContactPoint("EMAIL", "ada@example.org", True, now)],
        addresses=[Address(country_code="ES", city="Madrid")],
        consents=[Consent("PRIVACY_POLICY", "web", now)],
        preferences=CustomerPreferences(language_tag="es-ES", opt_in_email=True),
    )


def test_roundtrip_and_scope(db: Path, customer: Customer) -> None:
    with sqlite3.connect(db) as connection:
        repo = SqliteCustomerRepository(connection)
        with SqliteUnitOfWork(connection) as uow:
            repo.save(customer)
            with sqlite3.connect(db) as other:
                assert (
                    SqliteCustomerRepository(other).get(
                        tenant_id=customer.tenant_id,
                        business_id=customer.business_id,
                        customer_id=customer.id,
                    )
                    is None
                )
            uow.commit()
        assert (
            repo.get(
                tenant_id=customer.tenant_id,
                business_id=customer.business_id,
                customer_id=customer.id,
            )
            == customer
        )
        assert (
            repo.get(
                tenant_id=customer.tenant_id,
                business_id=BusinessId.generate(),
                customer_id=customer.id,
            )
            is None
        )
        assert (
            repo.get_by_external_ref(
                tenant_id=customer.tenant_id,
                business_id=customer.business_id,
                external_ref="reference-1",
            )
            == customer
        )
        assert (
            repo.get_by_external_ref(
                tenant_id=TenantId.generate(),
                business_id=customer.business_id,
                external_ref="reference-1",
            )
            is None
        )


def test_rollback_scope_and_unique_reference(db: Path, customer: Customer) -> None:
    with sqlite3.connect(db) as connection:
        repo = SqliteCustomerRepository(connection)
        with pytest.raises(RuntimeError, match="transacción"):
            repo.save(customer)
        with SqliteUnitOfWork(connection):
            repo.save(customer)
        assert (
            repo.get(
                tenant_id=customer.tenant_id,
                business_id=customer.business_id,
                customer_id=customer.id,
            )
            is None
        )
        with SqliteUnitOfWork(connection) as uow:
            repo.save(customer)
            uow.commit()
        with pytest.raises(ValueError, match="negocio"):
            with SqliteUnitOfWork(connection):
                repo.save(replace(customer, business_id=BusinessId.generate()))
        with pytest.raises(sqlite3.IntegrityError):
            with SqliteUnitOfWork(connection):
                repo.save(replace(customer, id=CustomerId.generate()))
        with SqliteUnitOfWork(connection) as uow:
            repo.save(
                replace(customer, id=CustomerId.generate(), business_id=BusinessId.generate())
            )
            uow.commit()


def test_search_filters_before_limit(db: Path, customer: Customer) -> None:
    location = LocationId.generate()
    scoped = replace(customer, id=CustomerId.generate(), external_ref=None, location_id=location)
    with sqlite3.connect(db) as connection:
        repo = SqliteCustomerRepository(connection)
        with SqliteUnitOfWork(connection) as uow:
            repo.save(customer)
            repo.save(scoped)
            uow.commit()
        params = dict(
            tenant_id=customer.tenant_id,
            business_id=customer.business_id,
            location_id=location,
            query="lovelace",
            status=CustomerStatus.ACTIVE,
            limit=1,
        )
        assert repo.search(**params) == [scoped]
        assert repo.search(**(params | {"tenant_id": TenantId.generate()})) == []
        assert repo.search(**(params | {"query": "%"})) == []
        with pytest.raises(ValueError, match="límite"):
            repo.search(**(params | {"limit": 0}))
