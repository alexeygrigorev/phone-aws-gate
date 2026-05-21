"""Unit tests for the gate logic (DDB-free)."""

from phone_aws_auth.gate import GateRow


def test_is_open_at_returns_true_for_active_unexpired():
    row = GateRow(
        token_hash="x",
        active=True,
        mode="sandbox",
        expires_at=1000,
        started_at=900,
    )
    assert row.is_open_at(999) is True
    assert row.is_open_at(900) is True


def test_is_open_at_returns_false_at_or_after_expiry():
    row = GateRow(
        token_hash="x",
        active=True,
        mode="sandbox",
        expires_at=1000,
        started_at=900,
    )
    assert row.is_open_at(1000) is False
    assert row.is_open_at(1001) is False


def test_is_open_at_returns_false_when_inactive():
    row = GateRow(
        token_hash="x",
        active=False,
        mode="sandbox",
        expires_at=10_000,
        started_at=900,
    )
    assert row.is_open_at(1000) is False
