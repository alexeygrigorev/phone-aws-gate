"""Client that opens/closes the gate by writing a DynamoDB row directly.

This is what the Android app will do, and what the CLI/Makefile and smoke
test use. The phone holds AWS credentials for a narrowly-scoped IAM user
whose policy permits only PutItem/DeleteItem/GetItem on a single gate row.

Local dev: point at DDB Local via endpoint_url + fake creds.
Real AWS:  rely on the standard boto3 credential chain (env, ~/.aws/...).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

import boto3
from botocore.exceptions import ClientError


@dataclass
class GateState:
    active: bool
    mode: str = ""
    started_at: int = 0
    expires_at: int = 0
    note: str = ""


class GateClient:
    """Reads and writes the single gate row by row_key (= token_hash)."""

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

    def start(self, mode: str, duration_minutes: int = 60, note: str = "") -> GateState:
        if mode != "sandbox":
            raise ValueError(f"mode must be 'sandbox', got {mode!r}")
        if duration_minutes <= 0 or duration_minutes > 24 * 60:
            raise ValueError(f"duration_minutes must be 1..1440, got {duration_minutes}")

        now = int(time.time())
        expires_at = now + duration_minutes * 60
        self._table.put_item(Item={
            "token_hash": self.row_key,
            "active": True,
            "mode": mode,
            "started_at": now,
            "expires_at": expires_at,
            "note": note[:200],
        })
        return GateState(
            active=True, mode=mode, started_at=now, expires_at=expires_at, note=note,
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
        )
