"""F3.22: test-only SHA-256 manifest checks for synthetic SQLite snapshots.

A digest verifies bytes against a trusted reference; it does NOT prove origin.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from test_staff_order_transitions import _counts, _setup, _status
from test_staff_sqlite_backup_restore import _backup, _verify_database


def _manifest(snapshot: Path) -> dict[str, str | int]:
    content = snapshot.read_bytes()
    return {
        "algorithm": "sha256",
        "bytes": len(content),
        "digest": hashlib.sha256(content).hexdigest(),
    }


def _check_manifest(snapshot: Path, expected: dict[str, str | int]) -> None:
    """Check snapshot bytes before any test restoration; never replace a DB."""
    if not snapshot.is_file():
        raise ValueError("Snapshot missing")
    if expected.get("algorithm") != "sha256":
        raise ValueError("Unsupported digest algorithm")
    size = expected.get("bytes")
    digest = expected.get("digest")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ValueError("Invalid manifest byte count")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("Invalid SHA-256 digest")
    try:
        bytes.fromhex(digest)
    except ValueError as exc:
        raise ValueError("Invalid SHA-256 digest") from exc
    content = snapshot.read_bytes()
    if len(content) != size:
        raise ValueError("Backup size differs from trusted manifest")
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError("Backup SHA-256 differs from trusted manifest")


@pytest.mark.parametrize(
    "damage",
    ("missing", "changed-bytes", "wrong-hash", "wrong-size", "bad-algorithm", "bad-digest"),
)
def test_manifest_rejects_modified_snapshot(tmp_path: Path, damage: str) -> None:
    source = tmp_path / "source.db"
    snapshot = tmp_path / "snapshot.db"
    destination = tmp_path / "destination.db"
    _client, _sessions, _csrf, order_id, other_id = _setup(str(source))
    _backup(source, snapshot)
    _backup(source, destination)
    trusted = _manifest(snapshot)
    before = destination.read_bytes()
    expected_counts = _counts(str(destination))

    if damage == "missing":
        snapshot.unlink()
    elif damage == "changed-bytes":
        changed = bytearray(snapshot.read_bytes())
        changed[-1] ^= 1
        snapshot.write_bytes(changed)
    elif damage == "wrong-hash":
        trusted["digest"] = "0" * 64
    elif damage == "wrong-size":
        trusted["bytes"] = int(trusted["bytes"]) + 1
    elif damage == "bad-algorithm":
        trusted["algorithm"] = "md5"
    elif damage == "bad-digest":
        trusted["digest"] = "xyz"

    with pytest.raises(ValueError):
        _check_manifest(snapshot, trusted)

    assert destination.read_bytes() == before
    _verify_database(destination)
    assert _counts(str(destination)) == expected_counts
    assert _status(str(destination), order_id) == "draft"
    assert _status(str(destination), other_id) == "draft"


def test_trusted_digest_accepts_unchanged_sqlite_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    snapshot = tmp_path / "snapshot.db"
    _client, _sessions, _csrf, order_id, _other_id = _setup(str(source))
    _backup(source, snapshot)
    expected = _manifest(snapshot)
    _check_manifest(snapshot, expected)
    _verify_database(snapshot)
    assert _status(str(snapshot), order_id) == "draft"


def test_recomputed_digest_cannot_authenticate_backup_origin(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    original = tmp_path / "original.db"
    rewritten = tmp_path / "rewritten.db"
    _setup(str(source))
    _backup(source, original)
    _backup(original, rewritten)
    # Both artifacts are valid SQLite files, but one is changed after copying.
    # An actor who can replace the file AND its unsigned manifest can compute
    # a matching SHA-256 value, so origin must remain unverified.
    with rewritten.open("ab") as output:
        output.write(b"untrusted append")
    original_manifest = _manifest(original)
    modified_manifest = _manifest(rewritten)
    with pytest.raises(ValueError):
        _check_manifest(rewritten, original_manifest)
    _check_manifest(rewritten, modified_manifest)
