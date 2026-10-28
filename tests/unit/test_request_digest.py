"""Contract tests for versioned idempotency request fingerprints."""

import os
import subprocess
import sys
from dataclasses import dataclass, replace
from decimal import Decimal

import pytest

from universal_business.application.catalog.commands import CreateOffering
from universal_business.application.idempotency import IdempotencyKey
from universal_business.application.request_digest import request_digest
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    OfferingId,
    TenantId,
)


def test_digest_tracks_request_scope_and_excludes_key() -> None:
    command = CreateOffering(
        tenant_id=TenantId.generate(),
        business_id=BusinessId.generate(),
        offering_id=OfferingId.generate(),
        name="Original",
        base_price=Decimal("1.25"),
        currency="EUR",
        location_ids=frozenset({LocationId.generate(), LocationId.generate()}),
        idempotency_key=IdempotencyKey(value="original-key"),
    )
    digest = request_digest(command)
    assert digest.startswith("v1:")
    assert digest == request_digest(
        replace(command, idempotency_key=IdempotencyKey(value="other-key"))
    )
    assert digest != request_digest(replace(command, name="Changed"))
    assert digest != request_digest(replace(command, business_id=BusinessId.generate()))


def test_digest_is_stable_across_processes_and_hash_seeds() -> None:
    script = """
from universal_business.application.catalog.commands import CreateOffering
from universal_business.application.request_digest import request_digest
from universal_business.domain.shared.value_objects.ids import TenantId, BusinessId, OfferingId, LocationId
c = CreateOffering(tenant_id=TenantId.from_raw("00000000-0000-0000-0000-000000000001"), business_id=BusinessId.from_raw("00000000-0000-0000-0000-000000000002"), offering_id=OfferingId.from_raw("00000000-0000-0000-0000-000000000003"), name="prueba", location_ids=frozenset(LocationId.from_raw(f"00000000-0000-0000-0000-{i:012d}") for i in range(4, 20)))
print(request_digest(c))
"""
    results = []
    for seed in ("1", "2", "137"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": "src"}
        results.append(subprocess.check_output([sys.executable, "-c", script], env=env, text=True))
    assert len(set(results)) == 1


def test_digest_rejects_unsupported_values() -> None:
    @dataclass(frozen=True)
    class Unsupported:
        field: object

    with pytest.raises(TypeError, match="Unsupported idempotency"):
        request_digest(Unsupported(field=object()))
    with pytest.raises(TypeError, match="Unsupported idempotency"):
        request_digest(Unsupported(field=1.0))
