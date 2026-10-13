"""Approval tokens for clinical writes (SPEC section 5; CLAUDE.md: FHIR create/update only after a
human-in-the-loop approval token).

A token is the doctor's approval of one draft, with exactly this content, for one patient, for a
short time: HMAC-SHA-256 over the canonical JSON of the claims with APPROVAL_TOKEN_KEY. `verify`
checks the signature in constant time, the time window and, when given, that the content about to
be written is the content that was approved (same SHA-256). Replays of a valid token do not create
a second resource: the write is a conditional create keyed on the draft id (fhir-mcp).
"""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import SecretStr

from agents.schemas import ApprovalClaims, ApprovalToken

DEFAULT_TTL = timedelta(minutes=10)
CLOCK_SKEW = timedelta(seconds=30)


class ApprovalError(Exception):
    """The write is refused; the message says why (never includes the key or the signature)."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def content_sha256(content: Any) -> str:
    """Hash of a draft's content (a dict, list or Pydantic model), as bound into the claims."""
    if hasattr(content, "model_dump"):
        content = content.model_dump(mode="json")
    return hashlib.sha256(canonical(content)).hexdigest()


def _key(key: SecretStr) -> bytes:
    raw = key.get_secret_value()
    if len(raw) < 32:
        raise ApprovalError("APPROVAL_TOKEN_KEY is missing or too short (run just gen-keys)")
    return raw.encode()


def _signature(claims: ApprovalClaims, key: SecretStr) -> str:
    return hmac.new(
        _key(key), canonical(claims.model_dump(mode="json")), hashlib.sha256
    ).hexdigest()


def sign(claims: ApprovalClaims, key: SecretStr) -> ApprovalToken:
    return ApprovalToken(claims=claims, signature=_signature(claims, key))


def approve(
    draft_id: str,
    content: Any,
    patient_id: str,
    approver: str,
    key: SecretStr,
    *,
    now: datetime | None = None,
    ttl: timedelta = DEFAULT_TTL,
) -> ApprovalToken:
    """Issue a token for a doctor's approval of `content` (the caller has checked the role)."""
    issued = now or datetime.now(UTC)
    claims = ApprovalClaims(
        draft_id=draft_id,
        draft_sha256=content_sha256(content),
        patient_id=patient_id,
        approver=approver,
        issued_at=issued,
        expires_at=issued + ttl,
    )
    return sign(claims, key)


def verify(
    token: ApprovalToken,
    key: SecretStr,
    *,
    now: datetime | None = None,
    content: Any = None,
) -> ApprovalClaims:
    """The claims if the token is genuine, current and, when `content` is given, for it."""
    expected = _signature(token.claims, key)
    if not hmac.compare_digest(expected, token.signature):
        raise ApprovalError("approval signature does not match")
    moment = now or datetime.now(UTC)
    if moment < token.claims.issued_at - CLOCK_SKEW:
        raise ApprovalError("approval is issued in the future")
    if moment >= token.claims.expires_at:
        raise ApprovalError("approval has expired")
    if content is not None and content_sha256(content) != token.claims.draft_sha256:
        raise ApprovalError("content differs from the approved draft")
    return token.claims
