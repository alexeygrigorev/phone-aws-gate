"""Push notification for new pending approval requests.

The phone approval flow previously only notified the owner while the phone app
was open (foreground DDB polling) or when the requesting host happened to have
a Telegram bot configured. This module closes that gap at the single choke
point every requester already goes through: the vendor Lambda that stores the
pending request. When a new pending request is created, the vendor pushes a
Telegram message to the owner's chat with requester, resource, reason, expiry
and a deep link to that exact request.

Notification is strictly best-effort: a delivery failure never fails or delays
the request itself, and it never grants anything. Real approve/deny stay
owner actions in the phone app or on the web approval page.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Callable, Optional

TELEGRAM_API_BASE = "https://api.telegram.org"
DEFAULT_APPROVE_BASE_URL = "https://tools.dtcdev.click"
DUPLICATE_WINDOW_SECONDS = 15 * 60


def approve_url_for(request_id: str, base_url: str = DEFAULT_APPROVE_BASE_URL) -> str:
    from urllib.parse import quote

    return f"{base_url.rstrip('/')}/approve?id={quote(str(request_id))}"


def format_request_message(record: dict, *, now: Optional[int] = None, base_url: str = DEFAULT_APPROVE_BASE_URL) -> str:
    now = int(now if now is not None else time.time())
    expires_at = int(record.get("expires_at", 0))
    remaining = max(0, expires_at - now)
    minutes = (remaining + 59) // 60
    expires_label = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(expires_at))
    return "\n".join([
        f"Cloud Gate approval request {record.get('id', '')}",
        f"Who asks: {record.get('requester', '')}",
        f"Resource: {record.get('resource', '')} ({record.get('scope', '')})",
        f"Why: {record.get('reason', '')}",
        f"Expires: {expires_label} (in {minutes} min)",
        "",
        f"Approve/Deny in the Cloud Gate phone app, or open this exact request:",
        approve_url_for(record.get("id", ""), base_url),
    ])


def recent_duplicate(record: dict) -> bool:
    """True when an equivalent pending request was pushed recently.

    Reads the same `pending:global` row the phone app polls. Retries that
    recreate the request with a fresh id must not spam the owner's phone.
    """
    try:
        from . import gate

        table = gate._ddb().Table(gate.config.GATE_TABLE_NAME)
        existing = (table.get_item(Key={"token_hash": "pending:global"}).get("Item") or {}).get("requests") or []
        now = int(time.time())
        for other in existing:
            if not isinstance(other, dict) or other.get("id") == record.get("id"):
                continue
            if str(other.get("state", "")) != "pending" or int(other.get("expires_at", 0)) <= now:
                continue
            same = (
                str(other.get("requester", "")) == str(record.get("requester", ""))
                and str(other.get("resource", "")) == str(record.get("resource", ""))
                and str(other.get("scope", "")) == str(record.get("scope", ""))
            )
            if same and int(record.get("requested_at", now)) - int(other.get("requested_at", 0)) < DUPLICATE_WINDOW_SECONDS:
                return True
        return False
    except Exception:
        return False


def notify_request_created(
    record: dict,
    *,
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
    base_url: Optional[str] = None,
    dedup: Optional[Callable[[dict], bool]] = None,
    poster: Optional[Callable[[str, str], dict]] = None,
    now: Optional[int] = None,
) -> dict:
    """Push one pending-request notification. Never raises; never grants."""
    try:
        bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
        base_url = base_url or os.environ.get("GATE_APPROVE_BASE_URL", DEFAULT_APPROVE_BASE_URL)
        if not bot_token or not chat_id:
            return {"notified": False, "reason": "not_configured"}
        if dedup is None:
            dedup = recent_duplicate
        if dedup(record):
            return {"notified": False, "reason": "duplicate_recent"}
        if poster is None:
            poster = _default_poster(bot_token)
        result = poster(chat_id, format_request_message(record, now=now, base_url=base_url))
        return {"notified": True, "message_id": result.get("message_id", "")}
    except Exception as e:  # noqa: BLE001 — notification must never break the request
        return {"notified": False, "reason": f"{type(e).__name__}"}


def _default_poster(bot_token: str) -> Callable[[str, str], dict]:
    def poster(chat: str, text: str) -> dict:
        payload = json.dumps({"chat_id": chat, "text": text}).encode("utf-8")
        req = urllib.request.Request(
            f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return json.loads(resp.read().decode("utf-8")).get("result", {})

    return poster
