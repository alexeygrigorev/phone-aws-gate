"""Tiny client for the control Lambda — used by the smoke test and CLI tools.

Mirrors what the Android app will do: sign requests with HMAC-SHA256, include
timestamp + nonce headers, parse JSON responses. Kept dependency-free so it
runs anywhere with the stdlib.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional

TIMESTAMP_HEADER = "X-Phone-Auth-Timestamp"
NONCE_HEADER = "X-Phone-Auth-Nonce"
SIGNATURE_HEADER = "X-Phone-Auth-Signature"


@dataclass
class Response:
    status: int
    body: Any

    def ok(self) -> bool:
        return 200 <= self.status < 300


class ControlClient:
    def __init__(self, base_url: str, hmac_secret: bytes, *, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.secret = hmac_secret
        self.timeout = timeout

    def _signed_call(self, method: str, path: str, body_obj: Optional[dict] = None) -> Response:
        body = json.dumps(body_obj).encode() if body_obj is not None else b""
        ts = int(time.time())
        nonce = secrets.token_hex(16)
        canon = f"{ts}\n{nonce}\n{method}\n{path}\n".encode() + body
        sig = hmac.new(self.secret, canon, hashlib.sha256).hexdigest()

        headers = {
            TIMESTAMP_HEADER: str(ts),
            NONCE_HEADER: nonce,
            SIGNATURE_HEADER: sig,
        }
        if body:
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(
            self.base_url + path,
            data=body if body else None,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = resp.read().decode()
                return Response(status=resp.status, body=_maybe_json(payload))
        except urllib.error.HTTPError as e:
            payload = e.read().decode()
            return Response(status=e.code, body=_maybe_json(payload))

    def start(self, mode: str, duration_minutes: int = 60, note: str = "") -> Response:
        return self._signed_call("POST", "/start", {
            "mode": mode,
            "duration_minutes": duration_minutes,
            "note": note,
        })

    def stop(self) -> Response:
        return self._signed_call("POST", "/stop")

    def status(self) -> Response:
        return self._signed_call("POST", "/status")


def _maybe_json(s: str) -> Any:
    try:
        return json.loads(s)
    except (ValueError, json.JSONDecodeError):
        return s
