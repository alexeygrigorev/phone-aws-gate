"""DynamoDB access for the gate table.

`phone-aws-gate`: PK `token_hash` (S). Single row at a time per token. TTL on
`expires_at` is a safety net; the vendor Lambda also checks expiry on read.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

import boto3

from . import config


def _ddb():
    endpoint = os.environ.get("DDB_ENDPOINT_URL")
    kwargs = {"region_name": config.REGION}
    if endpoint:
        kwargs["endpoint_url"] = endpoint
        kwargs.setdefault("aws_access_key_id", "local")
        kwargs.setdefault("aws_secret_access_key", "local")
    return boto3.resource("dynamodb", **kwargs)


@dataclass(frozen=True)
class GateRow:
    token_hash: str
    active: bool
    mode: str
    expires_at: int
    started_at: int
    note: str = ""

    def is_open_at(self, now: int) -> bool:
        return self.active and self.expires_at > now


def read_gate(token_hash: str) -> Optional[GateRow]:
    table = _ddb().Table(config.GATE_TABLE_NAME)
    resp = table.get_item(Key={"token_hash": token_hash})
    item = resp.get("Item")
    if not item:
        return None
    return GateRow(
        token_hash=item["token_hash"],
        active=bool(item.get("active", False)),
        mode=str(item.get("mode", "")),
        expires_at=int(item.get("expires_at", 0)),
        started_at=int(item.get("started_at", 0)),
        note=str(item.get("note", "")),
    )


def open_gate(token_hash: str, mode: str, duration_seconds: int, note: str = "") -> GateRow:
    now = int(time.time())
    row = GateRow(
        token_hash=token_hash,
        active=True,
        mode=mode,
        expires_at=now + duration_seconds,
        started_at=now,
        note=note,
    )
    table = _ddb().Table(config.GATE_TABLE_NAME)
    table.put_item(Item={
        "token_hash": row.token_hash,
        "active": row.active,
        "mode": row.mode,
        "expires_at": row.expires_at,
        "started_at": row.started_at,
        "note": row.note,
    })
    return row


def close_gate(token_hash: str) -> None:
    table = _ddb().Table(config.GATE_TABLE_NAME)
    table.delete_item(Key={"token_hash": token_hash})
