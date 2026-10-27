"""Local shim e2e: phone -> DynamoDB emulator -> HTTP vendor -> STS shim.

No AWS credentials or Docker resources are used. Also covers install defaults.
"""
import configparser
import datetime as dt
import hashlib
import json
from unittest.mock import patch

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from phone_aws_auth import gate
from phone_aws_auth.handlers import vendor
from shims.vendor_shim import app
from tools.phone_client import GateClient
from tools.install_aws_gate import update_aws_config


class StsShim:
    def __init__(self):
        self.calls = []
        self.sessions = {}

    def assume_role(self, **kwargs):
        self.calls.append(kwargs)
        key = f"ASIA{len(self.calls):016d}"
        self.sessions[key] = kwargs.get("Tags", [])
        return {"Credentials": {"AccessKeyId": key, "SecretAccessKey": "shim",
            "SessionToken": "shim", "Expiration": dt.datetime(2030, 1, 1, tzinfo=dt.UTC)}}

    def assume_main(self, credentials):
        tags = {t["Key"]: t["Value"] for t in self.sessions[credentials["AccessKeyId"]]}
        if tags.get("aws-gate-main") != "true" or not tags.get("aws-gate-grant"):
            raise PermissionError("AccessDenied")
        return "387546586013"


@mock_aws
def test_phone_vendor_main_stop_expiry(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    monkeypatch.setenv("SANDBOX_ROLE_ARN", "arn:aws:iam::817685572750:role/phone-aws-sandbox-role")
    monkeypatch.delenv("DDB_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("MOCK_STS", raising=False)
    table = boto3.resource("dynamodb", region_name="eu-west-1").create_table(
        TableName="phone-aws-gate", KeySchema=[{"AttributeName":"token_hash","KeyType":"HASH"}],
        AttributeDefinitions=[{"AttributeName":"token_hash","AttributeType":"S"}], BillingMode="PAY_PER_REQUEST")
    bearer = "local-main-test"
    key = hashlib.sha256(bearer.encode()).hexdigest()
    phone = GateClient(row_key=key)
    sts = StsShim()
    http = TestClient(app)
    def vend():
        return http.get("/", headers={"Authorization":bearer})
    with patch.object(vendor, "_sts", return_value=sts):
        phone.start("sandbox", main_access=False)
        unchecked = vend()
        assert unchecked.status_code == 200
        assert "Tags" not in sts.calls[-1]
        assert sts.calls[-1]["DurationSeconds"] == 900
        with pytest.raises(PermissionError, match="AccessDenied"):
            sts.assume_main(unchecked.json())
        phone.start("sandbox", main_access=True)
        assert phone.status().main_access is True
        checked = vend()
        assert checked.status_code == 200
        assert sts.assume_main(checked.json()) == "387546586013"
        assert sts.calls[-1]["Tags"][1]["Value"] == phone.status().grant_id
        count = len(sts.calls)
        # Use inactive row to represent Stop without deleting data.
        table.update_item(Key={"token_hash":key}, UpdateExpression="SET active = :v", ExpressionAttributeValues={":v":False})
        assert vend().status_code == 403
        phone.start("sandbox", main_access=True)
        table.update_item(Key={"token_hash":key}, UpdateExpression="SET expires_at = :v", ExpressionAttributeValues={":v":1})
        assert vend().status_code == 403
        assert len(sts.calls) == count
        # STS does not invalidate already-issued sessions on Stop.
        assert sts.assume_main(checked.json()) == "387546586013"
        table.update_item(Key={"token_hash":key}, UpdateExpression="SET expires_at = :v REMOVE main_access", ExpressionAttributeValues={":v":4000000000})
        assert gate.read_gate(key).main_access is False
        assert phone.status().main_access is False


def test_install_main_preserves_default(tmp_path):
    path = tmp_path / "config"
    path.write_text("[default]\nregion = eu-west-1\ncredential_process = gate-command\n")
    config = configparser.RawConfigParser()
    config.read(path)
    old = dict(config["default"])
    update_aws_config(path, region="eu-west-1", credential_command="gate-command")
    config.read(path)
    assert dict(config["default"]) == old
    assert config["profile main"]["source_profile"] == "default"
    assert config["profile main"]["duration_seconds"] == "900"
    assert config["profile main"]["role_arn"] == "arn:aws:iam::387546586013:role/aws-gate-main-access"
