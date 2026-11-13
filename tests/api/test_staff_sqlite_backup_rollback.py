"""F3.24: rollback detection using a trusted external sequence (test-only)."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import pytest
from test_staff_order_transitions import _counts, _setup, _status
from test_staff_sqlite_backup_digest import _check_manifest, _manifest
from test_staff_sqlite_backup_restore import _backup, _verify_database


_KEY = b"synthetic-rollback-hmac-key-material-32bytes"


def _canonical(manifest: dict[str, str | int]) -> bytes:
    fields = ("algorithm", "bytes", "digest", "key_id", "backup_id", "sequence")
    payload = {name: manifest[name] for name in fields}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sign_backup(path: Path, backup_id: str, sequence: int) -> dict[str, str | int]:
    if not backup_id or type(sequence) is not int or sequence < 1:
        raise ValueError("Invalid backup identity or sequence")
    manifest = {
        **_manifest(path),
        "key_id": "synthetic-key",
        "backup_id": backup_id,
        "sequence": sequence,
    }
    manifest["mac"] = hmac.new(_KEY, _canonical(manifest), hashlib.sha256).hexdigest()
    return manifest


def _verify_latest(
    path: Path,
    manifest: dict[str, str | int],
    *,
    trusted_sequence: int | None,
    trusted_backup_id: str | None,
) -> None:
    """Trusted checkpoint must be independent of the snapshot and manifest."""
    if trusted_sequence is None or trusted_backup_id is None:
        raise ValueError("Missing trusted external checkpoint")
    number = manifest.get("sequence")
    identity = manifest.get("backup_id")
    if type(number) is not int or number < 1:
        raise ValueError("Invalid sequence")
    if not isinstance(identity, str) or not identity:
        raise ValueError("Invalid backup identity")
    mac = manifest.get("mac")
    if not isinstance(mac, str) or len(mac) != 64:
        raise ValueError("Malformed MAC")
    try:
        bytes.fromhex(mac)
    except ValueError as exc:
        raise ValueError("Malformed MAC") from exc
    expected = hmac.new(_KEY, _canonical(manifest), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, mac):
        raise ValueError("Backup MAC mismatch")
    if number != trusted_sequence or identity != trusted_backup_id:
        raise ValueError("Stale or unexpected backup checkpoint")
    _check_manifest(path, manifest)


def _snapshots(tmp_path: Path) -> tuple[Path, Path, Path, str, str]:
    from apps.api.app.staff_auth import StaffRole
    from test_staff_order_transitions import FIRST_ROUTE, _authenticate, _headers

    source = tmp_path / "live.db"
    older = tmp_path / "older.db"
    newer = tmp_path / "newer.db"
    client, sessions, csrf, order_id, other_id = _setup(str(source))
    _backup(source, older)
    roles = frozenset({StaffRole.MANAGE_ORDERS})
    token = _authenticate(client, sessions, roles=roles)
    route = f"{FIRST_ROUTE}/{order_id}/transitions"
    response = client.post(
        route,
        json={"action": "validate"},
        headers=_headers(csrf, token, key="rollback-test-0001"),
    )
    assert response.status_code == 200
    _backup(source, newer)
    return older, newer, source, order_id, other_id


def test_valid_old_hmac_is_rejected_after_newer_checkpoint(tmp_path: Path) -> None:
    older, newer, source, order_id, other_id = _snapshots(tmp_path)
    first = _sign_backup(older, "backup-one", 1)
    second = _sign_backup(newer, "backup-two", 2)
    # The older backup is valid and authentic under its original checkpoint.
    _verify_latest(older, first, trusted_sequence=1, trusted_backup_id="backup-one")
    _verify_latest(newer, second, trusted_sequence=2, trusted_backup_id="backup-two")
    destination = tmp_path / "destination.db"
    _backup(newer, destination)
    before = destination.read_bytes()
    counts = _counts(str(destination))

    with pytest.raises(ValueError, match="Stale"):
        _verify_latest(older, first, trusted_sequence=2, trusted_backup_id="backup-two")

    assert destination.read_bytes() == before
    _verify_database(destination)
    assert _counts(str(destination)) == counts
    assert _status(str(destination), order_id) == "validated"
    assert _status(str(destination), other_id) == "draft"
    assert _status(str(source), order_id) == "validated"


@pytest.mark.parametrize("tamper", ("sequence", "backup-id", "missing-checkpoint"))
def test_rollback_metadata_cannot_be_forged(tmp_path: Path, tamper: str) -> None:
    _older, newer, _source, _order_id, _other_id = _snapshots(tmp_path)
    signed = _sign_backup(newer, "backup-two", 2)
    if tamper == "sequence":
        signed["sequence"] = 3
    elif tamper == "backup-id":
        signed["backup_id"] = "another-backup"

    checkpoint = None if tamper == "missing-checkpoint" else 2
    with pytest.raises(ValueError):
        _verify_latest(
            newer, signed, trusted_sequence=checkpoint, trusted_backup_id="backup-two"
        )


def test_equal_sequence_rejects_different_signed_backup_id(tmp_path: Path) -> None:
    _older, newer, _source, _order_id, _other_id = _snapshots(tmp_path)
    different = _sign_backup(newer, "other-signed-backup", 2)
    with pytest.raises(ValueError, match="unexpected"):
        _verify_latest(
            newer,
            different,
            trusted_sequence=2,
            trusted_backup_id="backup-two",
        )
