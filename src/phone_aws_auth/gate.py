"""DynamoDB gate state.

A single row per registered host token controls whether the vendor Lambda
mints credentials. Additional rows (`req:*`, `pending:*`, `grant:*`, `sms-*`)
coordinate phone-approved requests for AWS, browser/desktop, and SMS codes.
"""

from __future__ import annotations

import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import boto3

from . import config

SMS_CODE_RE = re.compile(r"\b(\d{4,8})\b")


def _ddb():
    endpoint = os.environ.get("DDB_ENDPOINT_URL")
    kwargs = {"region_name": config.REGION}
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return boto3.resource("dynamodb", **kwargs)


@dataclass(frozen=True)
class GateRow:
    token_hash: str
    active: bool
    mode: str
    started_at: int
    expires_at: int
    note: str = ""
    main_access: bool = False
    grant_id: str = ""

    def is_open_at(self, now: Optional[int] = None) -> bool:
        now = int(time.time()) if now is None else now
        return self.active and self.expires_at > now


def read_gate(token_hash: str) -> Optional[GateRow]:
    table = _ddb().Table(config.GATE_TABLE_NAME)
    resp = table.get_item(Key={"token_hash": token_hash}, ConsistentRead=True)
    item = resp.get("Item")
    if not item:
        return None
    return GateRow(
        token_hash=item["token_hash"],
        active=bool(item.get("active", False)),
        mode=str(item.get("mode", "")),
        started_at=int(item.get("started_at", 0)),
        expires_at=int(item.get("expires_at", 0)),
        note=str(item.get("note", "")),
        main_access=item.get("main_access") is True,
        grant_id=str(item.get("grant_id", "")),
    )


def open_gate(
    token_hash: str,
    mode: str,
    duration_seconds: int = config.DEFAULT_GATE_DURATION_SECONDS,
    note: str = "",
    main_access: bool = False,
    grant_id: str = "",
) -> GateRow:
    if mode not in config.ALLOWED_MODES:
        raise ValueError(f"mode must be one of {config.ALLOWED_MODES}, got {mode!r}")
    if duration_seconds <= 0 or duration_seconds > config.MAX_GATE_DURATION_SECONDS:
        raise ValueError(f"duration_seconds out of range: {duration_seconds}")

    now = int(time.time())
    grant_id = grant_id or uuid.uuid4().hex
    row = GateRow(
        token_hash=token_hash,
        active=True,
        mode=mode,
        started_at=now,
        expires_at=now + duration_seconds,
        note=note[:200],
        main_access=main_access,
        grant_id=grant_id,
    )
    table = _ddb().Table(config.GATE_TABLE_NAME)
    table.put_item(Item={
        "token_hash": row.token_hash,
        "active": row.active,
        "mode": row.mode,
        "started_at": row.started_at,
        "expires_at": row.expires_at,
        "note": row.note,
        "main_access": row.main_access,
        "grant_id": row.grant_id,
    })
    return row


def close_gate(token_hash: str) -> None:
    table = _ddb().Table(config.GATE_TABLE_NAME)
    table.delete_item(Key={"token_hash": token_hash})


def _append_pending(table, key: str, summary: dict, now: int) -> None:
    existing = (table.get_item(Key={"token_hash": key}).get("Item") or {}).get("requests") or []
    kept = [
        r for r in existing
        if isinstance(r, dict)
        and r.get("id") != summary["id"]
        and r.get("state") == "pending"
        and int(r.get("expires_at", 0)) > now
    ]
    kept.append(summary)
    table.put_item(Item={
        "token_hash": key,
        "requests": kept[-25:],
        "expires_at": now + config.MAX_GATE_DURATION_SECONDS,
    })


def create_request(
    host_token_hash: str,
    *,
    requester: str,
    resource: str,
    scope: str = "",
    reason: str,
    ttl_s: int,
    req_id: Optional[str] = None,
) -> dict:
    requester = (requester or "").strip()
    resource = (resource or "").strip()
    reason = (reason or "").strip()
    if not requester:
        raise ValueError("requester is required")
    if resource not in config.ALLOWED_RESOURCES:
        raise ValueError(f"resource must be one of {config.ALLOWED_RESOURCES}")
    scope = (scope or config.DEFAULT_SCOPES.get(resource, "default")).strip()
    if not scope:
        raise ValueError("scope is required")
    if not reason:
        raise ValueError("reason is required")
    ttl_s = int(ttl_s)
    if ttl_s < 60 or ttl_s > config.MAX_GATE_DURATION_SECONDS:
        raise ValueError(f"ttl_s must be between 60 and {config.MAX_GATE_DURATION_SECONDS}")

    now = int(time.time())
    request_id = req_id or uuid.uuid4().hex[:12]
    prompt_expires = now + config.REQUEST_PROMPT_TTL_SECONDS
    record = {
        "id": request_id,
        "host_token_hash": host_token_hash,
        "requester": requester[:120],
        "resource": resource,
        "scope": scope[:80],
        "reason": reason[:300],
        "ttl_s": ttl_s,
        "state": "pending",
        "requested_at": now,
        "expires_at": prompt_expires,
    }
    table = _ddb().Table(config.GATE_TABLE_NAME)
    table.put_item(Item={"token_hash": f"req:{request_id}", **record})
    _append_pending(table, f"pending:{host_token_hash}", record, now)
    _append_pending(table, "pending:global", record, now)
    return record


def check_grant(
    host_token_hash: str,
    resource: str,
    scope: str = "",
    *,
    since: int = 0,
) -> dict:
    if resource not in config.ALLOWED_RESOURCES:
        return {"granted": False, "resource": resource, "scope": scope, "reason": "invalid_resource"}
    scope = (scope or config.DEFAULT_SCOPES.get(resource, "default")).strip()
    now = int(time.time())
    table = _ddb().Table(config.GATE_TABLE_NAME)

    for key in (f"grant:{host_token_hash}:{resource}:{scope}", f"grant:global:{resource}:{scope}"):
        item = table.get_item(Key={"token_hash": key}).get("Item")
        if item and item.get("active") and int(item.get("expires_at", 0)) > now:
            started_at = int(item.get("started_at", 0))
            if since and started_at < since - 5:
                continue
            return {
                "granted": True,
                "resource": resource,
                "scope": scope,
                "grant_id": str(item.get("grant_id", "")),
                "expires_at": int(item["expires_at"]),
                "started_at": started_at,
                "requester": str(item.get("requester", "")),
                "reason": str(item.get("reason", "")),
            }

    host_item = table.get_item(Key={"token_hash": host_token_hash}).get("Item")
    if host_item and host_item.get("active") and int(host_item.get("expires_at", 0)) > now:
        started_at = int(host_item.get("started_at", 0))
        if not (since and started_at < since - 5):
            if resource == "aws-main" and host_item.get("main_access") is not True:
                return {"granted": False, "resource": resource, "scope": scope, "reason": "main_not_enabled"}
            allowed_resources = host_item.get("resources")
            if allowed_resources is None or resource in allowed_resources:
                return {
                    "granted": True,
                    "resource": resource,
                    "scope": scope,
                    "grant_id": str(host_item.get("grant_id", f"{host_token_hash}-{started_at}")),
                    "expires_at": int(host_item["expires_at"]),
                    "started_at": started_at,
                    "requester": str(host_item.get("requester", "phone")),
                    "reason": str(host_item.get("note", "")),
                }

    return {"granted": False, "resource": resource, "scope": scope, "reason": "no_active_grant"}


def get_request(host_token_hash: str, req_id: str) -> Optional[dict]:
    table = _ddb().Table(config.GATE_TABLE_NAME)
    item = table.get_item(Key={"token_hash": f"req:{req_id}"}).get("Item")
    if not item:
        return None
    now = int(time.time())
    state = str(item.get("state", "pending"))
    requested_at = int(item.get("requested_at", 0))
    expires_at = int(item.get("expires_at", 0))
    grant_expires_at = int(item.get("grant_expires_at", 0))
    grant_id = str(item.get("grant_id", ""))

    if state == "pending":
        check = check_grant(
            str(item.get("host_token_hash") or host_token_hash),
            str(item.get("resource", "")),
            str(item.get("scope", "")),
            since=requested_at,
        )
        if check.get("granted"):
            state = "approved"
            grant_expires_at = int(check.get("expires_at", 0))
            grant_id = str(check.get("grant_id", ""))
        elif expires_at <= now:
            state = "expired"

    return {
        "id": str(item.get("id", req_id)),
        "host_token_hash": str(item.get("host_token_hash", host_token_hash)),
        "requester": str(item.get("requester", "")),
        "resource": str(item.get("resource", "")),
        "scope": str(item.get("scope", "")),
        "reason": str(item.get("reason", "")),
        "ttl_s": int(item.get("ttl_s", 0)),
        "state": state,
        "requested_at": requested_at,
        "expires_at": expires_at,
        "grant_expires_at": grant_expires_at,
        "grant_id": grant_id,
    }


def sms_heartbeat(scope: str = "login") -> dict:
    scope = (scope or "login").strip()
    now = int(time.time())
    table = _ddb().Table(config.GATE_TABLE_NAME)
    table.put_item(Item={
        "token_hash": f"sms-hb:{scope}",
        "scope": scope,
        "updated_at": now,
        "expires_at": now + config.MAX_GATE_DURATION_SECONDS,
    })
    return {"ok": True, "scope": scope, "updated_at": now}


def sms_push(host_token_hash: str, scope: str, text: str, sender: str = "") -> dict:
    scope = (scope or "login").strip()
    grant = check_grant(host_token_hash, "sms", scope)
    if not grant.get("granted"):
        raise PermissionError("No active sms grant")
    match = SMS_CODE_RE.search(text or "")
    if not match:
        return {"stored": False, "reason": "no_code"}
    code = match.group(1)
    now = int(time.time())
    table = _ddb().Table(config.GATE_TABLE_NAME)
    table.put_item(Item={
        "token_hash": f"sms-code:{scope}",
        "scope": scope,
        "code": code,
        "sender": (sender or "")[:80],
        "received_at": now,
        "expires_at": min(now + 300, int(grant.get("expires_at", now + 300))),
    })
    return {"stored": True, "scope": scope}


def sms_poll(host_token_hash: str, scope: str = "login") -> dict:
    scope = (scope or "login").strip()
    grant = check_grant(host_token_hash, "sms", scope)
    if not grant.get("granted"):
        raise PermissionError("No active sms grant")
    now = int(time.time())
    table = _ddb().Table(config.GATE_TABLE_NAME)
    key = {"token_hash": f"sms-code:{scope}"}
    item = table.get_item(Key=key).get("Item")
    if not item or int(item.get("expires_at", 0)) <= now:
        return {"code": None, "scope": scope}
    table.delete_item(Key=key)
    return {
        "code": str(item.get("code", "")),
        "sender": str(item.get("sender", "")),
        "received_at": int(item.get("received_at", 0)),
        "scope": scope,
    }
