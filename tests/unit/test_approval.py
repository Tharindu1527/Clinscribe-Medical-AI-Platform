"""Approval tokens (Phase 3): genuine, current and bound to the exact content, or refused."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from agents.approval import ApprovalError, approve, content_sha256, verify

KEY = SecretStr("k" * 64)
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
RESOURCE = {"resourceType": "DocumentReference", "subject": {"reference": "Patient/p-1"}}


def test_valid_token_verifies_for_its_content() -> None:
    token = approve("draft-1", RESOURCE, "p-1", "dr-house", KEY, now=NOW)
    claims = verify(token, KEY, now=NOW + timedelta(minutes=5), content=RESOURCE)
    assert (claims.draft_id, claims.approver, claims.role) == ("draft-1", "dr-house", "doctor")
    assert claims.draft_sha256 == content_sha256(RESOURCE)


def test_key_order_does_not_change_the_hash() -> None:
    assert content_sha256({"a": 1, "b": [1, 2]}) == content_sha256({"b": [1, 2], "a": 1})


def test_tampered_claims_or_wrong_key_are_refused() -> None:
    token = approve("draft-1", RESOURCE, "p-1", "dr-house", KEY, now=NOW)
    forged = token.model_copy(
        update={"claims": token.claims.model_copy(update={"patient_id": "p-2"})}
    )
    with pytest.raises(ApprovalError, match="signature"):
        verify(forged, KEY, now=NOW)
    with pytest.raises(ApprovalError, match="signature"):
        verify(token, SecretStr("x" * 64), now=NOW)


def test_expired_future_and_changed_content_are_refused() -> None:
    token = approve("draft-1", RESOURCE, "p-1", "dr-house", KEY, now=NOW)
    with pytest.raises(ApprovalError, match="expired"):
        verify(token, KEY, now=NOW + timedelta(minutes=10))
    with pytest.raises(ApprovalError, match="future"):
        verify(token, KEY, now=NOW - timedelta(minutes=5))
    changed = {**RESOURCE, "status": "entered-in-error"}
    with pytest.raises(ApprovalError, match="differs"):
        verify(token, KEY, now=NOW, content=changed)


def test_a_missing_key_is_an_error_not_an_empty_signature() -> None:
    with pytest.raises(ApprovalError, match="APPROVAL_TOKEN_KEY"):
        approve("draft-1", RESOURCE, "p-1", "dr-house", SecretStr(""), now=NOW)
