"""Tests for the phone-side GateClient (input validation)."""

from __future__ import annotations

import pytest

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
