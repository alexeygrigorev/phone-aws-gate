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

    path = event.get("rawPath") or "/"
    if path not in ("/", "/main"):
        return _response(404, "Not found")
    if row.mode not in (*config.ALLOWED_MODES, "main"):
        return _response(500, f"Bad mode in gate row: {row.mode!r}")

    main = path == "/main"
    if (main and not row.main_access) or (not main and row.mode == "main"):
        return _response(403, "Account not granted")

    if os.environ.get("MOCK_STS") == "1":
        creds = _fake_creds("main" if main else row.mode)
    else:
        role_arn = config.role_arn_for_mode("sandbox" if main else row.mode)
        request_id = getattr(context, "aws_request_id", "local")
        assume_args = dict(
            RoleArn=role_arn,
            RoleSessionName=f"phone-{row.mode}-{request_id[:8]}",
            DurationSeconds=config.STS_SESSION_DURATION_SECONDS,
        )
        if row.main_access:
            assume_args["Tags"] = [
                {"Key": "aws-gate-main", "Value": "true"},
                {"Key": "aws-gate-grant", "Value": row.grant_id or f"{row.token_hash}-{row.started_at}"},
            ]
        resp = _sts().assume_role(**assume_args)
        c = resp["Credentials"]
        if main:
            c = boto3.client(
                "sts",
                region_name=config.REGION,
                aws_access_key_id=c["AccessKeyId"],
                aws_secret_access_key=c["SecretAccessKey"],
                aws_session_token=c["SessionToken"],
            ).assume_role(
                RoleArn=config.MAIN_ROLE_ARN,
                RoleSessionName=f"phone-main-{request_id[:8]}",
                DurationSeconds=900,
            )["Credentials"]
        creds = {
            "AccessKeyId": c["AccessKeyId"],
            "SecretAccessKey": c["SecretAccessKey"],
            "Token": c["SessionToken"],
            "Expiration": c["Expiration"].isoformat(),
        }

    log.info("vend grant_id=%s main_access=%s account=%s",
             row.grant_id or f"{row.token_hash}-{row.started_at}", row.main_access, "main" if main else row.mode)
    return _response(200, creds)


def _const_eq(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    diff = 0
    for x, y in zip(a, b):
        diff |= ord(x) ^ ord(y)
    return diff == 0
