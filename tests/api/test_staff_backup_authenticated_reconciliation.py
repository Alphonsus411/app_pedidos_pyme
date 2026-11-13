"""F3.27: authenticate backup bytes before considering a checkpoint confirmed."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from test_staff_backup_checkpoint_windows import (
    _finalize,
    _laboratory,
    _observe,
    _register,
    _snapshot,
)
from test_staff_checkpoint_monotonic import _publish_checkpoint, _read_checkpoint
from test_staff_sqlite_backup_hmac import _sign_backup, _verify_latest


def _observe_authenticated(
    ledger: Path,
    checkpoint: Path,
    artifact: Path,
    manifest: dict[str, str | int] | None,
    sequence: int,
    backup_id: str,
) -> str:
    """Read-only: never repair, publish or restore based on a filename alone."""
    state = _observe(ledger, checkpoint, artifact, sequence, backup_id)
    if state != "confirmed":
        return state
    if manifest is None:
        return "missing_manifest"
    trusted = _read_checkpoint(checkpoint)
    if trusted is None:
        return "missing_checkpoint"
    try:
        _verify_latest(
            artifact,
            manifest,
            trusted_sequence=trusted[0],
            trusted_backup_id=trusted[1],
        )
    except (ValueError, KeyError):
        return "authentication_failed"
    return "confirmed_authenticated"


def _confirmed_backup(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path, dict[str, str | int]]:
    source, ledger, checkpoint, artifact = _laboratory(tmp_path)
    _register(ledger, 1, "backup-one")
    _snapshot(source, artifact)
    manifest = _sign_backup(artifact, "backup-one", 1)
    _publish_checkpoint(checkpoint, 1, "backup-one")
    _finalize(ledger, 1, "backup-one")
    return source, ledger, checkpoint, artifact, manifest


def test_authenticated_backup_is_confirmed_without_changing_any_state(
    tmp_path: Path,
) -> None:
    source, ledger, checkpoint, artifact, manifest = _confirmed_backup(tmp_path)
    initial_backup = artifact.read_bytes()
    initial_source = source.read_bytes()
    state = _observe_authenticated(ledger, checkpoint, artifact, manifest, 1, "backup-one")
    assert state == "confirmed_authenticated"
    assert artifact.read_bytes() == initial_backup
    assert source.read_bytes() == initial_source
    assert _read_checkpoint(checkpoint) == (1, "backup-one")
    with sqlite3.connect(ledger) as connection:
        assert connection.execute("SELECT state FROM intents").fetchone() == ("confirmed",)


@pytest.mark.parametrize(
    "damage",
    (
        "missing-manifest",
        "wrong-manifest-id",
        "wrong-manifest-sequence",
        "wrong-mac",
        "modified-artifact",
        "swapped-valid-artifact",
    ),
)
def test_confirmed_backup_requires_matching_authenticated_bytes(
    tmp_path: Path, damage: str
) -> None:
    source, ledger, checkpoint, artifact, manifest = _confirmed_backup(tmp_path)
    destination = tmp_path / "untouched-destination.db"
    _snapshot(source, destination)
    destination_before = destination.read_bytes()
    source_before = source.read_bytes()
    if damage == "missing-manifest":
        manifest = None
    elif damage == "wrong-manifest-id":
        manifest = _sign_backup(artifact, "other-backup", 1)
    elif damage == "wrong-manifest-sequence":
        manifest = _sign_backup(artifact, "backup-one", 2)
    elif damage == "wrong-mac":
        manifest["mac"] = "0" * 64
    elif damage == "modified-artifact":
        with artifact.open("ab") as stream:
            stream.write(b"changed-after-signing")
    elif damage == "swapped-valid-artifact":
        with sqlite3.connect(source) as connection:
            connection.execute("INSERT INTO synthetic_orders(id) VALUES (2)")
        replacement = tmp_path / "other-valid-backup.db"
        _snapshot(source, replacement)
        artifact.write_bytes(replacement.read_bytes())
        with sqlite3.connect(artifact) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]

    status = _observe_authenticated(ledger, checkpoint, artifact, manifest, 1, "backup-one")
    expected = "missing_manifest" if damage == "missing-manifest" else "authentication_failed"
    assert status == expected
    assert _read_checkpoint(checkpoint) == (1, "backup-one")
    assert destination.read_bytes() == destination_before
    with sqlite3.connect(ledger) as connection:
        assert connection.execute("SELECT state FROM intents").fetchone() == ("confirmed",)
    if damage != "swapped-valid-artifact":
        assert source.read_bytes() == source_before


def test_pending_backup_cannot_be_promoted_by_valid_hmac(tmp_path: Path) -> None:
    source, ledger, checkpoint, artifact = _laboratory(tmp_path)
    _register(ledger, 1, "backup-one")
    _snapshot(source, artifact)
    manifest = _sign_backup(artifact, "backup-one", 1)
    status = _observe_authenticated(ledger, checkpoint, artifact, manifest, 1, "backup-one")
    assert status == "pending_unpublished"
    _publish_checkpoint(checkpoint, 1, "backup-one")
    status = _observe_authenticated(ledger, checkpoint, artifact, manifest, 1, "backup-one")
    assert status == "published_not_finalized"
    with sqlite3.connect(ledger) as connection:
        assert connection.execute("SELECT state FROM intents").fetchone() == ("pending",)
