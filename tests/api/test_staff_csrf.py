"""F3.10: contrato CSRF previo a mutaciones por sesión staff."""

from __future__ import annotations

import pytest
from apps.api.app.staff_csrf import CsrfRejected, StaffMutationCsrf

SESSION = "A" * 43
OTHER_SESSION = "B" * 43
ORIGIN = "https://panel.example.test"


def _guard() -> StaffMutationCsrf:
    return StaffMutationCsrf(secret=b"s" * 32, allowed_origins=[ORIGIN])


def _proof(guard: StaffMutationCsrf) -> str:
    return guard.issue_for_trusted_server(
        session_token=SESSION,
        business_slug="demo",
        location_slug="main",
        action="validate",
    )


def test_valid_origin_and_bound_proof_are_accepted() -> None:
    guard = _guard()
    proof = _proof(guard)
    assert len(proof) == 43
    guard.verify(
        origin=ORIGIN,
        session_token=SESSION,
        csrf_token=proof,
        business_slug="demo",
        location_slug="main",
        action="validate",
    )


@pytest.mark.parametrize(
    ("origin", "session", "business", "location", "action", "token_mode"),
    [
        (None, SESSION, "demo", "main", "validate", "correct"),
        ("https://evil.example.test", SESSION, "demo", "main", "validate", "correct"),
        ("http://panel.example.test", SESSION, "demo", "main", "validate", "correct"),
        (ORIGIN + "/", SESSION, "demo", "main", "validate", "correct"),
        (ORIGIN, OTHER_SESSION, "demo", "main", "validate", "correct"),
        (ORIGIN, SESSION, "other", "main", "validate", "correct"),
        (ORIGIN, SESSION, "demo", "branch", "validate", "correct"),
        (ORIGIN, SESSION, "demo", "main", "cancel", "correct"),
        (ORIGIN, SESSION, "demo", "main", "validate", "missing"),
        (ORIGIN, SESSION, "demo", "main", "validate", "forged"),
        (ORIGIN, SESSION, "demo", "main", "validate", "empty"),
    ],
)
def test_wrong_origin_session_scope_action_or_token_are_rejected(
    origin: str | None,
    session: str,
    business: str,
    location: str,
    action: str,
    token_mode: str,
) -> None:
    guard = _guard()
    proof = _proof(guard)
    if token_mode == "missing":
        token = None
    elif token_mode == "forged":
        token = "Z" * 43
    elif token_mode == "empty":
        token = ""
    else:
        token = proof
    with pytest.raises(CsrfRejected):
        guard.verify(
            origin=origin,
            session_token=session,
            csrf_token=token,
            business_slug=business,
            location_slug=location,
            action=action,
        )


@pytest.mark.parametrize(
    "origins",
    [
        [],
        ["http://panel.example.test"],
        ["https://panel.example.test/"],
        ["https://user:password@panel.example.test"],
        ["https://panel.example.test/path"],
        ["https://panel.example.test?x=1"],
        ["https://panel.example.test", "https://panel.example.test"],
    ],
)
def test_insecure_or_ambiguous_allowed_origins_are_rejected(origins: list[str]) -> None:
    with pytest.raises(ValueError):
        StaffMutationCsrf(secret=b"s" * 32, allowed_origins=origins)


@pytest.mark.parametrize("secret", [b"", b"short", b"s" * 31])
def test_short_secret_is_rejected(secret: bytes) -> None:
    with pytest.raises(ValueError):
        StaffMutationCsrf(secret=secret, allowed_origins=[ORIGIN])


@pytest.mark.parametrize("session", ["", "bad session", "é" * 43, "a" * 39])
def test_invalid_session_tokens_are_rejected(session: str) -> None:
    with pytest.raises(CsrfRejected):
        _guard().issue_for_trusted_server(
            session_token=session,
            business_slug="demo",
            location_slug="main",
            action="validate",
        )


def test_proof_uses_context_boundaries_and_not_session_plaintext() -> None:
    guard = _guard()
    token = _proof(guard)
    other = guard.issue_for_trusted_server(
        session_token=SESSION,
        business_slug="dem",
        location_slug="omain",
        action="validate",
    )
    assert token != other
    assert SESSION not in token
