"""Control Lambda — phone-driven /start, /stop, /status."""

from __future__ import annotations

import json
import logging
import os
import time

import boto3

from .. import auth, config, gate

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


def _response(status: int, body: dict | str) -> dict:
    payload = body if isinstance(body, str) else json.dumps(body)
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": payload,
    }


def _path_of(event: dict) -> str:
    return (
        (event.get("requestContext") or {}).get("http", {}).get("path")
        or event.get("rawPath")
        or event.get("path")
        or ""
    )


def _parse_body(event: dict) -> dict:
    raw = event.get("body") or ""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise auth.AuthError("invalid json body", status=400)


def handler(event: dict, context) -> dict:
    try:
        signed = auth.extract_signed_request(event)
        auth.verify(config.hmac_secret(), signed)
        if not gate.claim_nonce(signed.nonce):
            return _response(401, "Replay detected")

        path = _path_of(event)
        if path.endswith("/start"):
            return _handle_start(_parse_body(event))
        if path.endswith("/stop"):
            return _handle_stop()
        if path.endswith("/status"):
            return _handle_status()
        return _response(404, f"Unknown path: {path}")

    except auth.AuthError as e:
        log.warning("auth rejected: %s", e.reason)
        return _response(e.status, e.reason)
    except Exception as e:
        log.exception("unhandled error")
        return _response(500, f"Internal error: {type(e).__name__}")


def _handle_start(body: dict) -> dict:
    mode = body.get("mode")
    if mode not in config.ALLOWED_MODES:
        return _response(400, f"Bad mode: {mode!r}; expected one of {config.ALLOWED_MODES}")

    try:
        duration_minutes = int(body.get("duration_minutes", config.DEFAULT_GATE_DURATION_SECONDS // 60))
    except (TypeError, ValueError):
        return _response(400, "duration_minutes must be an integer")

    duration_seconds = duration_minutes * 60
    if duration_seconds <= 0:
        return _response(400, "duration must be positive")
    if duration_seconds > config.MAX_GATE_DURATION_SECONDS:
        return _response(400, f"duration exceeds max ({config.MAX_GATE_DURATION_SECONDS}s)")

    note = str(body.get("note", ""))[:200]

    row = gate.open_gate(
        token_hash=config.server_token_hash(),
        mode=mode,
        duration_seconds=duration_seconds,
        note=note,
    )
    return _response(200, {
        "active": True,
        "mode": row.mode,
        "started_at": row.started_at,
        "expires_at": row.expires_at,
    })


def _handle_stop() -> dict:
    gate.close_gate(config.server_token_hash())
    return _response(200, {"active": False})


def _handle_status() -> dict:
    resources_ok, details = _check_resources()
    row = gate.read_gate(config.server_token_hash())
    now = int(time.time())

    gate_state = None
    if row and row.is_open_at(now):
        gate_state = {
            "active": True,
            "mode": row.mode,
            "started_at": row.started_at,
            "expires_at": row.expires_at,
            "note": row.note,
        }

    return _response(200, {
        "stack_name": config.STACK_NAME,
        "region": config.REGION,
        "resources_ok": resources_ok,
        "prod_role_arn": os.environ.get("PROD_ROLE_ARN", ""),
        "sandbox_role_arn": os.environ.get("SANDBOX_ROLE_ARN", ""),
        "gate": gate_state,
        "details": details,
    })


def _check_resources() -> tuple[bool, dict]:
    """Verify the deployed resources exist. Used by /status."""
    if os.environ.get("SKIP_RESOURCE_CHECK") == "1":
        return True, {"skipped": True}

    iam = boto3.client("iam", region_name=config.REGION)
    ddb = boto3.client("dynamodb", region_name=config.REGION,
                       endpoint_url=os.environ.get("DDB_ENDPOINT_URL"))

    details = {}
    ok = True
    for role_name in (config.PROD_ROLE_NAME, config.SANDBOX_ROLE_NAME):
        try:
            iam.get_role(RoleName=role_name)
            details[role_name] = "ok"
        except Exception as e:
            details[role_name] = f"missing: {type(e).__name__}"
            ok = False

    for table_name in (config.GATE_TABLE_NAME, config.NONCE_TABLE_NAME):
        try:
            ddb.describe_table(TableName=table_name)
            details[table_name] = "ok"
        except Exception as e:
            details[table_name] = f"missing: {type(e).__name__}"
            ok = False

    return ok, details
