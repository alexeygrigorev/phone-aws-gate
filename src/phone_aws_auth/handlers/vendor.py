"""Vendor Lambda — mints short-lived STS credentials when the gate is open,
and coordinates phone-approved grant requests for AWS, browser/desktop, and SMS.

Wire format for GET / and GET /main follows the ECS container-credentials provider:
    https://docs.aws.amazon.com/sdkref/latest/guide/feature-container-credentials.html
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.parse

import boto3

from .. import config, gate, notify

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


def _method(event: dict) -> str:
    return (
        ((event.get("requestContext") or {}).get("http") or {}).get("method")
        or event.get("httpMethod")
        or "GET"
    ).upper()


def _query(event: dict) -> dict[str, str]:
    q = dict(event.get("queryStringParameters") or {})
    raw = event.get("rawQueryString") or ""
    if raw and not q:
        q = {k: v[-1] for k, v in urllib.parse.parse_qs(raw).items() if v}
    return {str(k): str(v) for k, v in q.items() if v is not None}


def _json_body(event: dict) -> dict:
    raw = event.get("body") or ""
    if not raw:
        return {}
    return json.loads(raw)


def _extract_token(raw_auth: str) -> str:
    val = (raw_auth or "").strip()
    if val.lower().startswith("bearer "):
        return val[7:].strip()
    return val


def handler(event: dict, context) -> dict:
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    token = _extract_token(headers.get("authorization") or "")
    if not token:
        return _response(403, "Forbidden")

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    path = (event.get("rawPath") or "/").rstrip("/") or "/"
    method = _method(event)

    if path == "/requests" and method == "POST":
        try:
            body = _json_body(event)
            req = gate.create_request(
                token_hash,
                requester=str(body.get("requester", "")),
                resource=str(body.get("resource", "")),
                scope=str(body.get("scope", "")),
                reason=str(body.get("reason", "")),
                ttl_s=int(body.get("ttl_s", 3600)),
            )
            notified = notify.notify_request_created(req)
            if not notified.get("notified"):
                log.info("push skipped request=%s reason=%s", req.get("id"), notified.get("reason"))
            return _response(201, {**req, "notified": bool(notified.get("notified"))})
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            return _response(400, {"error": "bad_request", "message": str(e)})

    if path.startswith("/requests/") and method == "GET":
        req_id = path.split("/requests/", 1)[1].strip("/")
        req = gate.get_request(token_hash, req_id)
        if not req:
            return _response(404, {"error": "not_found"})
        return _response(200, req)

    if path == "/check" and method == "GET":
        q = _query(event)
        target_hash = headers.get("x-host-row-key") or token_hash
        res = gate.check_grant(
            target_hash,
            resource=q.get("resource", "browser"),
            scope=q.get("scope", ""),
        )
        return _response(200, res)

    if path == "/sms/heartbeat" and method == "POST":
        body = _json_body(event)
        return _response(200, gate.sms_heartbeat(str(body.get("scope", "login"))))

    if path == "/sms/push" and method == "POST":
        try:
            body = _json_body(event)
            res = gate.sms_push(
                token_hash,
                scope=str(body.get("scope", "login")),
                text=str(body.get("text", "")),
                sender=str(body.get("sender", "")),
            )
            return _response(200, res)
        except PermissionError as e:
            return _response(403, {"error": "denied", "message": str(e)})

    if path == "/sms/poll" and method == "GET":
        try:
            q = _query(event)
            return _response(200, gate.sms_poll(token_hash, scope=q.get("scope", "login")))
        except PermissionError as e:
            return _response(403, {"error": "denied", "message": str(e)})

    row = gate.read_gate(token_hash)
    now = int(time.time())
    if row is None or not row.is_open_at(now):
        return _response(403, "Gate closed")

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

    if main:
        creds["Account"] = "main"

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
