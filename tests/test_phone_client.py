"""Tests for the phone-side GateClient (input validation and request approval/denial)."""

from __future__ import annotations

import hashlib
import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from shims.vendor_shim import app
from tools.phone_client import GateClient


@pytest.fixture
def client():
    # endpoint_url is set so boto3 doesn't try to reach real AWS during
    # construction; tests only exercise input validation, not network calls.
    return GateClient(
        row_key="x" * 64,
        endpoint_url="http://invalid.local:0",
    )


def test_start_rejects_unknown_mode(client):
    with pytest.raises(ValueError, match="mode must be"):
        client.start("midnight", duration_minutes=5)


def test_start_rejects_zero_duration(client):
    with pytest.raises(ValueError, match="duration_minutes"):
        client.start("sandbox", duration_minutes=0)


def test_start_rejects_too_long_duration(client):
    with pytest.raises(ValueError, match="duration_minutes"):
        client.start("sandbox", duration_minutes=24 * 60 + 1)


@mock_aws
def test_phone_request_approve_deny_and_check_flow(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    monkeypatch.setenv("SANDBOX_ROLE_ARN", "arn:aws:iam::817685572750:role/phone-aws-sandbox-role")
    monkeypatch.delenv("DDB_ENDPOINT_URL", raising=False)

    boto3.resource("dynamodb", region_name="eu-west-1").create_table(
        TableName="phone-aws-gate",
        KeySchema=[{"AttributeName": "token_hash", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "token_hash", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )

    bearer = "agent-host-bearer"
    row_key = hashlib.sha256(bearer.encode("utf-8")).hexdigest()
    phone = GateClient(row_key=row_key)
    http = TestClient(app)

    # 1. Agent checks browser:desktop before approval -> denied
    chk0 = http.get("/check?resource=browser&scope=desktop", headers={"Authorization": bearer})
    assert chk0.status_code == 200
    assert chk0.json()["granted"] is False

    # 2. Agent requests browser:desktop approval
    req_resp = http.post(
        "/requests",
        headers={"Authorization": bearer},
        json={
            "requester": "gate-hub-resilience-3",
            "resource": "browser",
            "scope": "desktop",
            "reason": "Verify Orin desktop browser health",
            "ttl_s": 1800,
        },
    )
    assert req_resp.status_code == 201
    req_data = req_resp.json()
    req_id = req_data["id"]
    assert req_data["state"] == "pending"
    assert req_data["requester"] == "gate-hub-resilience-3"
    assert req_data["resource"] == "browser"
    assert req_data["scope"] == "desktop"
    assert req_data["reason"] == "Verify Orin desktop browser health"
    assert req_data["ttl_s"] == 1800

    # 3. Phone lists pending requests -> sees who asks, resource, why, and duration
    pending = phone.list_pending_requests()
    assert len(pending) == 1
    assert pending[0]["id"] == req_id
    assert pending[0]["requester"] == "gate-hub-resilience-3"

    # 4. Phone approves request
    approved = phone.approve_request(req_id)
    assert approved["state"] == "approved"
    assert phone.list_pending_requests() == []

    # 5. Agent polls request status and /check -> approved & granted
    st_resp = http.get(f"/requests/{req_id}", headers={"Authorization": bearer})
    assert st_resp.status_code == 200
    assert st_resp.json()["state"] == "approved"

    chk1 = http.get("/check?resource=browser&scope=desktop", headers={"Authorization": bearer})
    assert chk1.status_code == 200
    assert chk1.json()["granted"] is True

    # 6. Second request denied by phone -> state=denied and grant revoked
    req2_resp = http.post(
        "/requests",
        headers={"Authorization": bearer},
        json={
            "requester": "relay-link-stats",
            "resource": "browser",
            "scope": "desktop",
            "reason": "Inspect Relay dashboard",
            "ttl_s": 900,
        },
    )
    req2_id = req2_resp.json()["id"]
    denied = phone.deny_request(req2_id)
    assert denied["state"] == "denied"

    st2_resp = http.get(f"/requests/{req2_id}", headers={"Authorization": bearer})
    assert st2_resp.json()["state"] == "denied"
    chk2 = http.get("/check?resource=browser&scope=desktop", headers={"Authorization": bearer})
    assert chk2.json()["granted"] is False
