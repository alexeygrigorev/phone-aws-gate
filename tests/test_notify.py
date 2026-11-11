"""Tests for the vendor-side push notification of new pending requests."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from urllib.error import URLError

from phone_aws_auth import notify


def _record(**overrides) -> dict:
    now = int(time.time())
    record = {
        "id": "abcd1234efgh",
        "host_token_hash": "h" * 64,
        "requester": "orin-vale",
        "resource": "browser",
        "scope": "desktop",
        "reason": "verify a rendering bug on the desktop browser",
        "ttl_s": 900,
        "state": "pending",
        "requested_at": now,
        "expires_at": now + 900,
    }
    record.update(overrides)
    return record


def test_message_contains_requester_resource_reason_expiry_and_deep_link():
    now = 1794414400
    text = notify.format_request_message(_record(expires_at=now + 900), now=now)
    assert "orin-vale" in text
    assert "browser (desktop)" in text
    assert "verify a rendering bug" in text
    assert "Expires:" in text
    assert "in 15 min" in text
    assert f"approve?id={_record()['id']}" in text


def test_approve_url_uses_configured_base():
    assert notify.approve_url_for("id1", "https://gate.example.com").startswith("https://gate.example.com/approve?id=id1")


def test_noop_without_configuration(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    calls = []
    result = notify.notify_request_created(
        _record(),
        poster=lambda chat, text: calls.append((chat, text)) or {"message_id": 1},
        dedup=lambda record: False,
    )
    assert result == {"notified": False, "reason": "not_configured"}
    assert calls == []


def test_pushes_with_configured_channel(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat-1")
    sent = {}

    def fake_poster(chat, text):
        sent["chat"], sent["text"] = chat, text
        return {"message_id": 42}

    result = notify.notify_request_created(_record(), poster=fake_poster, dedup=lambda record: False)
    assert result == {"notified": True, "message_id": 42}
    assert sent["chat"] == "chat-1"
    assert "orin-vale" in sent["text"]


def test_delivery_failure_never_raises(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat-1")

    def boom(chat, text):
        raise URLError("network down")

    result = notify.notify_request_created(_record(), poster=boom, dedup=lambda record: False)
    assert result["notified"] is False
    assert result["reason"] == "URLError"


def test_recent_duplicate_suppresses_push(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat-1")
    result = notify.notify_request_created(
        _record(),
        poster=lambda chat, text: (_ for _ in ()).throw(AssertionError("must not post")),
        dedup=lambda record: True,
    )
    assert result == {"notified": False, "reason": "duplicate_recent"}


def test_recent_duplicate_returns_false_on_store_failure(monkeypatch):
    class BoomTable:
        def get_item(self, key):
            raise RuntimeError("ddb down")

    from phone_aws_auth import gate

    monkeypatch.setattr(gate, "_ddb", lambda: SimpleNamespace(Table=lambda name: BoomTable()))
    assert notify.recent_duplicate(_record()) is False


def test_default_poster_sends_telegram_payload(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"ok": True, "result": {"message_id": 7}}).encode()

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())
        return FakeResponse()

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    poster = notify._default_poster("bot-token")
    result = poster("chat-9", "hello")
    assert result == {"message_id": 7}
    assert captured["url"] == "https://api.telegram.org/botbot-token/sendMessage"
    assert captured["body"] == {"chat_id": "chat-9", "text": "hello"}
