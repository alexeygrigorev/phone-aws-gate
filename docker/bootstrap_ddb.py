"""Create the gate + nonces tables in DynamoDB Local.

Idempotent: skips tables that already exist. Retries until DDB Local is reachable.
"""

from __future__ import annotations

import os
import sys
import time

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError

ENDPOINT = os.environ.get("DDB_ENDPOINT_URL", "http://dynamodb-local:8000")
REGION = os.environ.get("AWS_DEFAULT_REGION", "eu-west-1")

GATE_TABLE = "phone-aws-gate"
NONCE_TABLE = "phone-aws-nonces"


def wait_for_ddb(client, timeout: int = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            client.list_tables()
            return
        except (EndpointConnectionError, ClientError) as e:
            print(f"  waiting for DDB Local at {ENDPOINT}... ({type(e).__name__})")
            time.sleep(1)
    raise SystemExit(f"timed out waiting for DDB Local at {ENDPOINT}")


def ensure_table(client, name: str, key_schema: list, attr_defs: list) -> None:
    try:
        client.describe_table(TableName=name)
        print(f"  {name}: already exists")
        return
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise

    client.create_table(
        TableName=name,
        KeySchema=key_schema,
        AttributeDefinitions=attr_defs,
        BillingMode="PAY_PER_REQUEST",
    )
    waiter = client.get_waiter("table_exists")
    waiter.wait(TableName=name)
    print(f"  {name}: created")


def main() -> None:
    print(f"Connecting to DDB at {ENDPOINT} (region {REGION})")
    client = boto3.client(
        "dynamodb",
        endpoint_url=ENDPOINT,
        region_name=REGION,
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )
    wait_for_ddb(client)

    ensure_table(
        client,
        GATE_TABLE,
        [{"AttributeName": "token_hash", "KeyType": "HASH"}],
        [{"AttributeName": "token_hash", "AttributeType": "S"}],
    )
    ensure_table(
        client,
        NONCE_TABLE,
        [{"AttributeName": "nonce", "KeyType": "HASH"}],
        [{"AttributeName": "nonce", "AttributeType": "S"}],
    )

    # TTL is best-effort for tests; DDB Local supports it from 2.x onwards.
    for table_name, attr in [(GATE_TABLE, "expires_at"), (NONCE_TABLE, "expires_at")]:
        try:
            client.update_time_to_live(
                TableName=table_name,
                TimeToLiveSpecification={"AttributeName": attr, "Enabled": True},
            )
        except ClientError as e:
            print(f"  {table_name}: TTL enable skipped ({e.response['Error']['Code']})")

    print("bootstrap done")


if __name__ == "__main__":
    main()
