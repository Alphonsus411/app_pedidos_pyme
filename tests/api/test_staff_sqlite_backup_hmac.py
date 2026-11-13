"""F3.23: HMAC authentication of synthetic SQLite backup manifests (tests only)."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import pytest
from test_staff_order_transitions import _counts, _setup, _status
from test_staff_sqlite_backup_digest import _check_manifest, _manifest
from test_staff_sqlite_backup_restore import _backup, _verify_database


def _payload(manifest: dict[str, str | int]) -> bytes:
    fields = ("algorithm", "bytes", "digest", "key_id")
    values = {field: manifest[field] for field in fields}
    return json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sign(snapshot: Path, key_id: str, secret: bytes) -> dict[str, str | int]:
    if not key_id or len(secret) < 32:
        raise ValueError("Invalid synthetic signing configuration")
    manifest = {**_manifest(snapshot), "key_id": key_id}
    computed_mac = hmac.new(secret, _payload(manifest), hashlib.sha256)
    manifest["mac"] = computed_mac.hexdigest()
    return manifest


def _verify(
    snapshot: Path,
    manifest: dict[str, str | int],
    allowed_keys: dict[str, bytes],
) -> None:
    key_id = manifest.get("key_id")
    mac = manifest.get("mac")
    if not isinstance(key_id, str) or key_id not in allowed_keys:
        raise ValueError("Unknown or retired signing key")
    if not isinstance(mac, str) or len(mac) != 64:
        raise ValueError("Malformed backup MAC")
    try:
        bytes.fromhex(mac)
    except ValueError as exc:
        raise ValueError("Malformed backup MAC") from exc
    expected = hmac.new(allowed_keys[key_id], _payload(manifest), hashlib.sha256)
    if not hmac.compare_digest(expected.hexdigest(), mac):
        raise ValueError("Backup manifest MAC verification failed")
    _check_manifest(snapshot, manifest)


@pytest.mark.parametrize(
    "tamper",
    ("file", "size", "digest", "key-id", "mac", "missing-mac", "wrong-key"),
)
def test_hmac_tampering_preserves_destination(tmp_path: Path, tamper: str) -> None:
    source = tmp_path / "source.db"
    snapshot = tmp_path / "snapshot.db"
    destination = tmp_path / "destination.db"
    _client, _sessions, _csrf, order_id, other_id = _setup(str(source))
    _backup(source, snapshot)
    _backup(source, destination)
    before = destination.read_bytes()
    counts = _counts(str(destination))
    secret = b"synthetic-hmac-key-a-32-bytes-minimum"
    manifest = _sign(snapshot, "key-A", secret)
    trusted_keys = {"key-A": secret}

    if tamper == "file":
        with snapshot.open("ab") as output:
            output.write(b"modified backup")
    elif tamper == "size":
        manifest["bytes"] = int(manifest["bytes"]) + 1
    elif tamper == "digest":
        manifest["digest"] = "0" * 64
    elif tamper == "key-id":
        manifest["key_id"] = "key-B"
    elif tamper == "mac":
        manifest["mac"] = "0" * 64
    elif tamper == "missing-mac":
        manifest.pop("mac")
    elif tamper == "wrong-key":
        trusted_keys["key-A"] = b"another-synthetic-key-with-32-bytes"

    with pytest.raises(ValueError):
        _verify(snapshot, manifest, trusted_keys)

    assert destination.read_bytes() == before
    _verify_database(destination)
    assert _counts(str(destination)) == counts
    assert _status(str(destination), order_id) == "draft"
    assert _status(str(destination), other_id) == "draft"


def test_rotation_accepts_old_and_new_then_retires_old(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    backup = tmp_path / "backup.db"
    _setup(str(source))
    _backup(source, backup)
    old_secret = b"synthetic-rotation-old-key-32bytes"
    new_secret = b"synthetic-rotation-new-key-32bytes"
    older = _sign(backup, "key-2025", old_secret)
    newer = _sign(backup, "key-2026", new_secret)

    during_rotation = {"key-2025": old_secret, "key-2026": new_secret}
    _verify(backup, older, during_rotation)
    _verify(backup, newer, during_rotation)
    after_retirement = {"key-2026": new_secret}
    with pytest.raises(ValueError, match="retired"):
        _verify(backup, older, after_retirement)
    _verify(backup, newer, after_retirement)


def test_recomputed_digest_cannot_forge_mac(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    original = tmp_path / "original.db"
    modified = tmp_path / "modified.db"
    _setup(str(source))
    _backup(source, original)
    _backup(original, modified)
    secret = b"synthetic-hmac-integrity-key-32bytes"
    genuine = _sign(original, "key-A", secret)
    with modified.open("ab") as output:
        output.write(b"untrusted modification")
    rewritten = {**_manifest(modified), "key_id": "key-A", "mac": genuine["mac"]}
    with pytest.raises(ValueError, match="MAC"):
        _verify(modified, rewritten, {"key-A": secret})


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
