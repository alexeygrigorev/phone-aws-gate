"""HMAC authentication for the control Lambda.

Wire format (all required, all on requests from the phone):

    X-Phone-Auth-Timestamp: <unix seconds, integer as string>
    X-Phone-Auth-Nonce:     <random hex, 16+ chars>
    X-Phone-Auth-Signature: <hex sha256-hmac>

The signature covers, in order, the bytes:

    timestamp || "\\n" || nonce || "\\n" || method || "\\n" || path || "\\n" || body

The control Lambda rejects requests whose timestamp is outside
HMAC_TIMESTAMP_WINDOW_SECONDS of "now", and rejects nonces it has already seen
within that window (via a DynamoDB conditional put against `phone-aws-nonces`).
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass

from . import config


TIMESTAMP_HEADER = "x-phone-auth-timestamp"
NONCE_HEADER = "x-phone-auth-nonce"
SIGNATURE_HEADER = "x-phone-auth-signature"


@dataclass(frozen=True)
class SignedRequest:
    timestamp: int
    nonce: str
    signature: str
    method: str
    path: str
    body: bytes


def canonical_bytes(req: SignedRequest) -> bytes:
    return (
        f"{req.timestamp}\n{req.nonce}\n{req.method}\n{req.path}\n".encode("utf-8")
        + req.body
    )


def sign(secret: bytes, req: SignedRequest) -> str:
    return hmac.new(secret, canonical_bytes(req), hashlib.sha256).hexdigest()


class AuthError(Exception):
    def __init__(self, reason: str, status: int = 401):
        super().__init__(reason)
        self.reason = reason
        self.status = status


def extract_signed_request(event: dict) -> SignedRequest:
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}

    try:
        timestamp = int(headers[TIMESTAMP_HEADER])
        nonce = headers[NONCE_HEADER]
        signature = headers[SIGNATURE_HEADER]
    except (KeyError, ValueError) as e:
        raise AuthError(f"missing or malformed auth header: {e}") from e

    method = (event.get("requestContext") or {}).get("http", {}).get("method") \
        or event.get("httpMethod") or ""
    path = (event.get("requestContext") or {}).get("http", {}).get("path") \
        or event.get("rawPath") or event.get("path") or ""
    body = (event.get("body") or "").encode("utf-8")

    return SignedRequest(
        timestamp=timestamp,
        nonce=nonce,
        signature=signature,
        method=method,
        path=path,
        body=body,
    )


def verify(
    secret: bytes,
    req: SignedRequest,
    *,
    now: int | None = None,
    window: int = config.HMAC_TIMESTAMP_WINDOW_SECONDS,
) -> None:
    now = now if now is not None else int(time.time())
    if abs(now - req.timestamp) > window:
        raise AuthError("timestamp outside validity window")

    expected = sign(secret, req)
    if not hmac.compare_digest(expected, req.signature):
        raise AuthError("bad signature", status=403)
