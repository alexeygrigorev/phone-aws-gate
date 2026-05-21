"""Vendor Lambda — mints short-lived STS credentials when the gate is open.

Wire format follows the ECS container-credentials provider:
    https://docs.aws.amazon.com/sdkref/latest/guide/feature-container-credentials.html
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time

import boto3

from .. import config, gate

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


def _sts():
    endpoint = os.environ.get("STS_ENDPOINT_URL")
    kwargs = {"region_name": config.REGION}
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return boto3.client("sts", **kwargs)


def _fake_creds(mode: str) -> dict:
    expires = int(time.time()) + config.STS_SESSION_DURATION_SECONDS
    return {
        "AccessKeyId": f"ASIA-FAKE-{mode.upper()}",
        "SecretAccessKey": "fake-secret-not-real",
        "Token": f"fake-token-{mode}",
        "Expiration": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expires)),
    }


def _response(status: int, body: dict | str) -> dict:
    payload = body if isinstance(body, str) else json.dumps(body)
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": payload,
    }


def handler(event: dict, context) -> dict:
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    token = (headers.get("authorization") or "").strip()
    if not token:
        return _response(403, "Forbidden")

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    row = gate.read_gate(token_hash)
    now = int(time.time())
    if row is None or not row.is_open_at(now):
        return _response(403, "Gate closed")

    if row.mode not in config.ALLOWED_MODES:
        return _response(500, f"Bad mode in gate row: {row.mode!r}")

    if os.environ.get("MOCK_STS") == "1":
        creds = _fake_creds(row.mode)
    else:
        role_arn = config.role_arn_for_mode(row.mode)
        request_id = getattr(context, "aws_request_id", "local")
        resp = _sts().assume_role(
            RoleArn=role_arn,
            RoleSessionName=f"phone-{row.mode}-{request_id[:8]}",
            DurationSeconds=config.STS_SESSION_DURATION_SECONDS,
        )
        c = resp["Credentials"]
        creds = {
            "AccessKeyId": c["AccessKeyId"],
            "SecretAccessKey": c["SecretAccessKey"],
            "Token": c["SessionToken"],
            "Expiration": c["Expiration"].isoformat(),
        }

    return _response(200, creds)


def _const_eq(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    diff = 0
    for x, y in zip(a, b):
        diff |= ord(x) ^ ord(y)
    return diff == 0
