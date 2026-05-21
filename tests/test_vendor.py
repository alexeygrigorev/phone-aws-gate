"""Tests for the vendor Lambda handler.

The handler is pure aside from DDB + STS calls — we mock those.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from phone_aws_auth import gate
from phone_aws_auth.handlers import vendor


BEARER = "test-bearer-token"
TOKEN_HASH = hashlib.sha256(BEARER.encode()).hexdigest()


@pytest.fixture(autouse=True)
def env():
    """Set the env vars the handler reads on each call."""
    keys = {
        "SERVER_TOKEN_HASH": TOKEN_HASH,
        "SANDBOX_ROLE_ARN": "arn:aws:iam::000000000000:role/phone-aws-sandbox-role",
        "MOCK_STS": "1",
    }
    with patch.dict(os.environ, keys, clear=False):
        yield


def _event(token: str | None = BEARER) -> dict:
    headers = {"authorization": token} if token else {}
    return {"headers": headers}


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(aws_request_id="testreq-1234")


def _open_gate(mode: str = "sandbox", offset_seconds: int = 300) -> gate.GateRow:
    now = int(time.time())
    return gate.GateRow(
        token_hash=TOKEN_HASH,
        active=True,
        mode=mode,
        expires_at=now + offset_seconds,
        started_at=now,
    )


def test_403_when_no_authorization_header():
    resp = vendor.handler(_event(token=None), _ctx())
    assert resp["statusCode"] == 403


def test_403_when_token_hash_does_not_match():
    resp = vendor.handler(_event(token="wrong-bearer"), _ctx())
    assert resp["statusCode"] == 403


def test_403_when_gate_row_missing():
    with patch.object(gate, "read_gate", return_value=None):
        resp = vendor.handler(_event(), _ctx())
    assert resp["statusCode"] == 403
    assert "Gate closed" in resp["body"]


def test_403_when_gate_expired():
    expired = gate.GateRow(
        token_hash=TOKEN_HASH,
        active=True,
        mode="sandbox",
        expires_at=int(time.time()) - 1,
        started_at=int(time.time()) - 100,
    )
    with patch.object(gate, "read_gate", return_value=expired):
        resp = vendor.handler(_event(), _ctx())
    assert resp["statusCode"] == 403


def test_200_returns_fake_creds_for_sandbox():
    with patch.object(gate, "read_gate", return_value=_open_gate("sandbox")):
        resp = vendor.handler(_event(), _ctx())
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["AccessKeyId"] == "ASIA-FAKE-SANDBOX"
    assert "SecretAccessKey" in body
    assert "Token" in body
    assert "Expiration" in body


def test_500_when_gate_has_bad_mode():
    bad = gate.GateRow(
        token_hash=TOKEN_HASH,
        active=True,
        mode="midnight",  # not in ALLOWED_MODES
        expires_at=int(time.time()) + 300,
        started_at=int(time.time()),
    )
    with patch.object(gate, "read_gate", return_value=bad):
        resp = vendor.handler(_event(), _ctx())
    assert resp["statusCode"] == 500
