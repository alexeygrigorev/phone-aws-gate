"""Client that opens/closes the gate and approves/denies requests by writing to DynamoDB directly.

This is what the Android phone app does, and what the CLI/Makefile and smoke
test use. The phone holds AWS credentials for a narrowly-scoped IAM user
whose policy permits only PutItem/DeleteItem/GetItem on the `phone-aws-gate` table.

Local dev: point at DDB Local via endpoint_url + fake creds.
Real AWS:  rely on the standard boto3 credential chain (env, ~/.aws/...).
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import boto3
from botocore.exceptions import ClientError

ALLOWED_RESOURCES = ("aws-sandbox", "aws-main", "browser", "sms")
DEFAULT_SCOPES = {
    "aws-sandbox": "sandbox",
    "aws-main": "main",
    "browser": "desktop",
    "sms": "login",
}


@dataclass
class GateState:
    active: bool
    mode: str = ""
    started_at: int = 0
    expires_at: int = 0
    note: str = ""
    main_access: bool = False
    grant_id: str = ""


class GateClient:
    """Reads and writes the gate and resource grant rows by row_key (= token_hash)."""

    def __init__(
        self,
        *,
        row_key: str,
        table_name: str = "phone-aws-gate",
        region: str = "eu-west-1",
        endpoint_url: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
    ):
        self.row_key = row_key
        self.table_name = table_name

        kwargs = {"region_name": region}
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        if aws_access_key_id and aws_secret_access_key:
            kwargs["aws_access_key_id"] = aws_access_key_id
            kwargs["aws_secret_access_key"] = aws_secret_access_key
        elif endpoint_url:
            # DDB Local accepts anything as long as creds are present.
            kwargs.setdefault("aws_access_key_id", "local")
            kwargs.setdefault("aws_secret_access_key", "local")
        self._table = boto3.resource("dynamodb", **kwargs).Table(self.table_name)

    @classmethod
    def from_env(cls) -> "GateClient":
        return cls(
            row_key=os.environ["PHONE_AWS_ROW_KEY"],
            table_name=os.environ.get("PHONE_AWS_TABLE", "phone-aws-gate"),
            region=os.environ.get("AWS_DEFAULT_REGION", "eu-west-1"),
            endpoint_url=os.environ.get("DDB_ENDPOINT_URL") or None,
        )

    def start(self, mode: str, duration_minutes: int = 60, note: str = "", main_access: bool = False) -> GateState:
        if mode != "sandbox":
            raise ValueError(f"mode must be 'sandbox', got {mode!r}")
        if duration_minutes <= 0 or duration_minutes > 24 * 60:
            raise ValueError(f"duration_minutes must be 1..1440, got {duration_minutes}")

        now = int(time.time())
        expires_at = now + duration_minutes * 60
        grant_id = uuid.uuid4().hex
        self._table.put_item(Item={
            "token_hash": self.row_key,
            "active": True,
            "mode": mode,
            "started_at": now,
            "expires_at": expires_at,
            "note": note[:200],
            "main_access": main_access,
            "grant_id": grant_id,
        })
        return GateState(
            active=True, mode=mode, started_at=now, expires_at=expires_at, note=note,
            main_access=main_access, grant_id=grant_id,
        )

    def stop(self) -> None:
        self._table.delete_item(Key={"token_hash": self.row_key})

    def status(self) -> GateState:
        """Return current gate state. active=False if row is missing or expired."""
        try:
            resp = self._table.get_item(Key={"token_hash": self.row_key})
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "?")
            raise RuntimeError(f"DynamoDB error: {code}") from e

        item = resp.get("Item")
        if not item:
            return GateState(active=False)

        now = int(time.time())
        active = bool(item.get("active")) and int(item.get("expires_at", 0)) > now
        return GateState(
            active=active,
            mode=str(item.get("mode", "")),
            started_at=int(item.get("started_at", 0)),
            expires_at=int(item.get("expires_at", 0)),
            note=str(item.get("note", "")),
            main_access=item.get("main_access") is True,
            grant_id=str(item.get("grant_id", "")),
        )

    def open_resource_grant(
        self,
        resource: str,
        scope: str = "",
        *,
        duration_seconds: int = 3600,
        requester: str = "phone",
        reason: str = "",
        request_id: str = "",
        host_token_hash: Optional[str] = None,
    ) -> dict:
        if resource not in ALLOWED_RESOURCES:
            raise ValueError(f"resource must be one of {ALLOWED_RESOURCES}, got {resource!r}")
        if duration_seconds < 60 or duration_seconds > 24 * 3600:
            raise ValueError(f"duration_seconds must be 60..86400, got {duration_seconds}")
        scope = (scope or DEFAULT_SCOPES.get(resource, "default")).strip()
        target_hash = host_token_hash or self.row_key
        now = int(time.time())
        expires_at = now + duration_seconds
        grant_id = uuid.uuid4().hex
        row = {
            "active": True,
            "resource": resource,
            "scope": scope,
            "requester": requester[:120],
            "reason": reason[:300],
            "started_at": now,
            "expires_at": expires_at,
            "grant_id": grant_id,
            "request_id": request_id,
        }
        self._table.put_item(Item={"token_hash": f"grant:{target_hash}:{resource}:{scope}", **row})
        self._table.put_item(Item={"token_hash": f"grant:global:{resource}:{scope}", **row})
        if resource in ("aws-sandbox", "aws-main"):
            self._table.put_item(Item={
                "token_hash": target_hash,
                "active": True,
                "mode": "sandbox",
                "started_at": now,
                "expires_at": expires_at,
                "note": reason[:200],
                "main_access": resource == "aws-main",
                "grant_id": grant_id,
                "requester": requester[:120],
            })
        return row

    def close_resource_grant(self, resource: str, scope: str = "", *, host_token_hash: Optional[str] = None) -> None:
        scope = (scope or DEFAULT_SCOPES.get(resource, "default")).strip()
        target_hash = host_token_hash or self.row_key
        self._table.delete_item(Key={"token_hash": f"grant:{target_hash}:{resource}:{scope}"})
        self._table.delete_item(Key={"token_hash": f"grant:global:{resource}:{scope}"})
        if resource in ("aws-sandbox", "aws-main"):
            self._table.delete_item(Key={"token_hash": target_hash})

    def list_pending_requests(self, include_global: bool = True) -> list[dict]:
        now = int(time.time())
        seen: set[str] = set()
        results: list[dict] = []
        keys = [f"pending:{self.row_key}"]
        if include_global:
            keys.append("pending:global")
        for key in keys:
            item = self._table.get_item(Key={"token_hash": key}).get("Item") or {}
            for summary in item.get("requests") or []:
                req_id = str(summary.get("id", ""))
                if not req_id or req_id in seen:
                    continue
                seen.add(req_id)
                req = self._table.get_item(Key={"token_hash": f"req:{req_id}"}).get("Item")
                if not req:
                    continue
                if req.get("state") == "pending" and int(req.get("expires_at", 0)) > now:
                    results.append({
                        "id": req_id,
                        "host_token_hash": str(req.get("host_token_hash", self.row_key)),
                        "requester": str(req.get("requester", "")),
                        "resource": str(req.get("resource", "")),
                        "scope": str(req.get("scope", "")),
                        "reason": str(req.get("reason", "")),
                        "ttl_s": int(req.get("ttl_s", 3600)),
                        "state": "pending",
                        "requested_at": int(req.get("requested_at", 0)),
                        "expires_at": int(req.get("expires_at", 0)),
                    })
        results.sort(key=lambda r: r["requested_at"], reverse=True)
        return results

    def _remove_from_pending(self, host_token_hash: str, request_id: str) -> None:
        now = int(time.time())
        for key in (f"pending:{host_token_hash}", "pending:global"):
            item = self._table.get_item(Key={"token_hash": key}).get("Item")
            if not item:
                continue
            requests = [
                r for r in (item.get("requests") or [])
                if isinstance(r, dict) and r.get("id") != request_id and int(r.get("expires_at", 0)) > now
            ]
            self._table.put_item(Item={
                "token_hash": key,
                "requests": requests,
                "expires_at": now + 86400,
            })

    def approve_request(self, request_id: str, duration_seconds: Optional[int] = None) -> dict:
        req = self._table.get_item(Key={"token_hash": f"req:{request_id}"}).get("Item")
        if not req:
            raise ValueError(f"Unknown request: {request_id}")
        host_token_hash = str(req.get("host_token_hash") or self.row_key)
        resource = str(req["resource"])
        scope = str(req.get("scope") or DEFAULT_SCOPES.get(resource, "default"))
        ttl_s = int(duration_seconds or req.get("ttl_s") or 3600)
        requester = str(req.get("requester", ""))
        reason = str(req.get("reason", ""))

        grant = self.open_resource_grant(
            resource,
            scope,
            duration_seconds=ttl_s,
            requester=requester,
            reason=reason,
            request_id=request_id,
            host_token_hash=host_token_hash,
        )
        now = int(time.time())
        updated = {
            **req,
            "token_hash": f"req:{request_id}",
            "state": "approved",
            "decided_at": now,
            "grant_expires_at": grant["expires_at"],
            "grant_id": grant["grant_id"],
            "expires_at": max(int(req.get("expires_at", 0)), grant["expires_at"]),
        }
        self._table.put_item(Item=updated)
        self._remove_from_pending(host_token_hash, request_id)
        return updated

    def deny_request(self, request_id: str) -> dict:
        req = self._table.get_item(Key={"token_hash": f"req:{request_id}"}).get("Item")
        if not req:
            raise ValueError(f"Unknown request: {request_id}")
        host_token_hash = str(req.get("host_token_hash") or self.row_key)
        resource = str(req.get("resource", ""))
        scope = str(req.get("scope") or DEFAULT_SCOPES.get(resource, "default"))
        if resource in ALLOWED_RESOURCES:
            self.close_resource_grant(resource, scope, host_token_hash=host_token_hash)
        now = int(time.time())
        updated = {
            **req,
            "token_hash": f"req:{request_id}",
            "state": "denied",
            "decided_at": now,
        }
        self._table.put_item(Item=updated)
        self._remove_from_pending(host_token_hash, request_id)
        return updated
