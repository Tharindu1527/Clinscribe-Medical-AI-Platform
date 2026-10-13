"""Bearer tokens and role-based access (SPEC section 8: RBAC doctor / admin / operator).

A token is base64url(JSON {u, r, exp}) + "." + hex HMAC-SHA-256 with AUTH_TOKEN_KEY. Users and their
roles come from config/users.yaml (synthetic demo users); a token whose role no longer matches the
file is refused. Endpoints declare the roles they accept with `require(...)`.
"""

import base64
import hashlib
import hmac
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

import yaml
from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, SecretStr

from config.settings import Settings

USERS_FILE = Path(__file__).resolve().parents[2] / "config" / "users.yaml"
Role = Literal["doctor", "admin", "operator"]


class Principal(BaseModel):
    user: str
    role: Role


def users() -> dict[str, Role]:
    data = yaml.safe_load(USERS_FILE.read_text(encoding="utf-8"))
    return {name: info["role"] for name, info in data["users"].items()}


def _key(key: SecretStr) -> bytes:
    raw = key.get_secret_value()
    if len(raw) < 32:
        raise RuntimeError("AUTH_TOKEN_KEY is missing or too short (run just gen-keys)")
    return raw.encode()


def issue_token(
    user: str, key: SecretStr, *, now: datetime | None = None, ttl: timedelta = timedelta(hours=8)
) -> str:
    role = users()[user]
    expires = (now or datetime.now(UTC)) + ttl
    body = json.dumps({"u": user, "r": role, "exp": int(expires.timestamp())}, sort_keys=True)
    payload = base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")
    signature = hmac.new(_key(key), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def read_token(token: str, key: SecretStr, *, now: datetime | None = None) -> Principal:
    payload, _, signature = token.partition(".")
    expected = hmac.new(_key(key), payload.encode(), hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(expected, signature):
        raise ValueError("bad token signature")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    if (now or datetime.now(UTC)).timestamp() >= claims["exp"]:
        raise ValueError("token expired")
    if users().get(claims["u"]) != claims["r"]:
        raise ValueError("user or role no longer valid")
    return Principal(user=claims["u"], role=claims["r"])


def principal(authorization: Annotated[str | None, Header()] = None) -> Principal:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    try:
        return read_token(authorization.removeprefix("Bearer "), Settings().auth_token_key)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(401, str(exc)) from None


def require(*roles: Role) -> Callable[[Principal], Principal]:
    def check(who: Annotated[Principal, Depends(principal)]) -> Principal:
        if who.role not in roles:
            raise HTTPException(403, f"role {who.role} may not do this")
        return who

    return check


if __name__ == "__main__":  # just token <user>
    print(issue_token(sys.argv[1], Settings().auth_token_key))
