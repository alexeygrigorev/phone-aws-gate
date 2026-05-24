"""Tests for the inline vendor Lambda embedded in CloudFormation."""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "infra" / "template.yaml"
BEARER = "test-bearer-token"
TOKEN_HASH = hashlib.sha256(BEARER.encode("utf-8")).hexdigest()


class FakeTable:
    def __init__(self, item: dict | None):
        self.item = item
        self.key = None

    def get_item(self, *, Key: dict) -> dict:
        self.key = Key
        return {"Item": self.item} if self.item else {}


class FakeDynamoResource:
    def __init__(self, table: FakeTable):
        self.table = table

    def Table(self, name: str) -> FakeTable:
        assert name == "phone-aws-gate"
        return self.table


class FakeStsClient:
    def __init__(self):
        self.assume_role_kwargs = None

    def assume_role(self, **kwargs) -> dict:
        self.assume_role_kwargs = kwargs
        return {
            "Credentials": {
                "AccessKeyId": "ASIAINLINE",
                "SecretAccessKey": "secret",
                "SessionToken": "token",
                "Expiration": dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            },
        }


class FakeBoto3(ModuleType):
    def __init__(self, table: FakeTable, sts: FakeStsClient):
        super().__init__("boto3")
        self.table = table
        self.sts = sts

    def resource(self, service: str):
        assert service == "dynamodb"
        return FakeDynamoResource(self.table)

    def client(self, service: str):
        assert service == "sts"
        return self.sts


def _inline_lambda_code() -> str:
    lines = TEMPLATE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "ZipFile: |") + 1
    body: list[str] = []
    for line in lines[start:]:
        if not line:
            body.append("")
            continue
        if not line.startswith("          "):
            break
        body.append(line[10:])
    return "\n".join(body)


def _load_handler(item: dict | None):
    table = FakeTable(item)
    sts = FakeStsClient()
    module_globals: dict = {}
    env = {
        "SANDBOX_ROLE_ARN": "arn:aws:iam::000000000000:role/phone-aws-sandbox-role",
        "SESSION_DURATION": "900",
    }
    with patch.dict(os.environ, env, clear=False), patch.dict(sys.modules, {"boto3": FakeBoto3(table, sts)}):
        exec(_inline_lambda_code(), module_globals)
    return module_globals["handler"], table, sts


def _event(token: str | None = BEARER) -> dict:
    return {"headers": {"authorization": token}} if token else {"headers": {}}


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(aws_request_id="testreq-1234")


def _open_item(mode: str = "sandbox", expires_at: int = 4_000_000_000) -> dict:
    return {
        "token_hash": TOKEN_HASH,
        "active": True,
        "mode": mode,
        "expires_at": expires_at,
        "started_at": 100,
    }


def test_inline_lambda_returns_403_when_authorization_missing():
    handler, _, _ = _load_handler(_open_item())

    resp = handler(_event(token=None), _ctx())

    assert resp["statusCode"] == 403


def test_inline_lambda_reads_row_by_token_hash():
    handler, table, _ = _load_handler(_open_item())

    handler(_event(), _ctx())

    assert table.key == {"token_hash": TOKEN_HASH}


def test_inline_lambda_returns_403_when_gate_missing_or_expired():
    missing_handler, _, _ = _load_handler(None)
    expired_handler, _, _ = _load_handler(_open_item(expires_at=1))

    assert missing_handler(_event(), _ctx())["statusCode"] == 403
    assert expired_handler(_event(), _ctx())["statusCode"] == 403


def test_inline_lambda_assumes_sandbox_role_when_gate_is_open():
    handler, _, sts = _load_handler(_open_item())

    resp = handler(_event(), _ctx())

    assert resp["statusCode"] == 200
    assert sts.assume_role_kwargs == {
        "RoleArn": "arn:aws:iam::000000000000:role/phone-aws-sandbox-role",
        "RoleSessionName": "phone-sandbox-testreq-",
        "DurationSeconds": 900,
    }
    assert "ASIAINLINE" in resp["body"]


def test_inline_lambda_rejects_bad_mode():
    handler, _, _ = _load_handler(_open_item(mode="prod"))

    resp = handler(_event(), _ctx())

    assert resp["statusCode"] == 500
