"""LiveKit room tokens for the browser's Voice tab (ADR-0019).

A LiveKit access token is an HS256 JWT signed with the API secret: issuer = API key, subject =
the participant's identity, and a "video" grant naming the one room it may join. Written here
(15 lines) rather than adding the livekit-api package to the API image.
"""

import base64
import hashlib
import hmac
import json
import time

from pydantic import SecretStr

TTL_S = 15 * 60  # long enough to join; the room's media session outlives the token


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def room_token(
    api_key: SecretStr, api_secret: SecretStr, identity: str, room: str, now: float | None = None
) -> str:
    key, secret = api_key.get_secret_value(), api_secret.get_secret_value()
    if not key or not secret:
        raise RuntimeError("LIVEKIT_API_KEY / LIVEKIT_API_SECRET are missing (run just gen-keys)")
    issued = int(now if now is not None else time.time())
    claims = {
        "iss": key,
        "sub": identity,
        "name": identity,
        "nbf": issued,
        "exp": issued + TTL_S,
        "video": {
            "room": room,
            "roomJoin": True,
            "canPublish": True,
            "canSubscribe": True,
            "canPublishData": True,
        },
    }
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(claims, separators=(",", ":")).encode())
    signature = hmac.new(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    return f"{header}.{body}.{_b64(signature)}"
