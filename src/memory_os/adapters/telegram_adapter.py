"""
Optional adapter for the Telegram Bot API (https://core.telegram.org/bots/api).

No extra dependencies — uses stdlib urllib.request. Set TELEGRAM_BOT_TOKEN in .env.

Security rules:
- Token is never logged, printed, or included in audit() output.
- parse_update() is pure data parsing — no network, no side effects.
- send_message() uses HTTPS only; rejects non-HTTPS schemes at construction time.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional


_BASE = "https://api.telegram.org"


def is_available() -> bool:
    """Always True: only stdlib is required."""
    return True


class TelegramAdapter:
    """Thin wrapper around the Telegram Bot API REST interface.

    Supports:
    - send_message(chat_id, text) — send a text reply.
    - get_updates(offset) — long-polling (one-shot, not a loop).
    - parse_update(payload) — pure parsing of a webhook/poll payload.
    - audit() — offline availability check (no network, no token in output).
    """

    def __init__(self, token: Optional[str] = None, timeout: float = 10.0) -> None:
        self._token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._api_id = os.environ.get("TELEGRAM_API_ID", "")
        self._api_hash = os.environ.get("TELEGRAM_API_HASH", "")
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def send_message(
        self,
        chat_id,
        text: str,
        parse_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a text message to a chat.

        Args:
            chat_id: Telegram chat or user ID (int or str).
            text: Message body (max 4096 chars per Telegram limits).
            parse_mode: Optional "Markdown" or "HTML".

        Returns:
            {"ok": True, "message_id": int} on success.
            {"ok": False, "detail": str} on any error.
        """
        if not self._token:
            return {"ok": False, "detail": "TELEGRAM_BOT_TOKEN not set"}
        if not text or not str(text).strip():
            return {"ok": False, "detail": "text must not be empty"}

        payload: Dict[str, Any] = {"chat_id": chat_id, "text": str(text)[:4096]}
        if parse_mode:
            payload["parse_mode"] = parse_mode

        return self._post("sendMessage", payload)

    def get_updates(self, offset: Optional[int] = None, limit: int = 100) -> Dict[str, Any]:
        """Fetch pending updates via long-polling (single request, not a loop).

        Args:
            offset: Update ID to start from (previous update_id + 1 to ACK).
            limit: Max updates to return (1-100).

        Returns:
            {"ok": True, "updates": list[dict]} or {"ok": False, "detail": str}.
        """
        if not self._token:
            return {"ok": False, "detail": "TELEGRAM_BOT_TOKEN not set"}

        params: Dict[str, Any] = {"limit": max(1, min(100, limit)), "timeout": 0}
        if offset is not None:
            params["offset"] = offset

        return self._get("getUpdates", params)

    def parse_update(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Parse a raw Telegram update (from webhook or getUpdates) into a normalized dict.

        Pure function — no network, no side effects.

        Returns a dict with platform-neutral fields plus a 'raw' key for full access:
        {
            "platform": "telegram",
            "update_id": int | None,
            "message_id": int | None,
            "chat_id": int | None,
            "user_id": int | None,
            "username": str | None,
            "text": str | None,
            "raw": dict
        }
        """
        try:
            msg = payload.get("message") or payload.get("edited_message") or {}
            sender = msg.get("from") or {}
            chat = msg.get("chat") or {}
            return {
                "platform": "telegram",
                "update_id": payload.get("update_id"),
                "message_id": msg.get("message_id"),
                "chat_id": chat.get("id"),
                "user_id": sender.get("id"),
                "username": sender.get("username") or sender.get("first_name"),
                "text": msg.get("text"),
                "raw": payload,
            }
        except Exception as exc:
            return {
                "platform": "telegram",
                "update_id": None,
                "message_id": None,
                "chat_id": None,
                "user_id": None,
                "username": None,
                "text": None,
                "raw": payload,
                "parse_error": str(exc),
            }

    def set_webhook(self, url: str) -> Dict[str, Any]:
        """Register a HTTPS webhook URL with Telegram.

        Args:
            url: Public HTTPS URL Telegram will POST updates to.

        Returns:
            {"ok": True} or {"ok": False, "detail": str}.
        """
        if not self._token:
            return {"ok": False, "detail": "TELEGRAM_BOT_TOKEN not set"}
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https":
            return {"ok": False, "detail": "webhook url must use https"}
        return self._post("setWebhook", {"url": url})

    def delete_webhook(self) -> Dict[str, Any]:
        """Remove the registered webhook (switches back to getUpdates mode)."""
        if not self._token:
            return {"ok": False, "detail": "TELEGRAM_BOT_TOKEN not set"}
        return self._post("deleteWebhook", {})

    def audit(self) -> Dict[str, Any]:
        """Offline availability report — no network call, token value never exposed."""
        return {
            "available": True,
            "token_configured": bool(self._token),
            "bot_api_base": _BASE,
            "note": "install: no extra package needed (stdlib urllib only)",
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _post(self, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{_BASE}/bot{self._token}/{method}"
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = json.loads(resp.read().decode())
                if not body.get("ok"):
                    return {"ok": False, "detail": body.get("description", "unknown error")}
                result = body.get("result", {})
                if isinstance(result, dict):
                    return {"ok": True, **result}
                return {"ok": True, "result": result}
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode())
                return {"ok": False, "detail": body.get("description", str(exc))}
            except Exception:
                return {"ok": False, "detail": str(exc)}
        except Exception as exc:
            return {"ok": False, "detail": f"telegram api call failed: {exc}"}

    def _get(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{_BASE}/bot{self._token}/{method}?{qs}"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = json.loads(resp.read().decode())
                if not body.get("ok"):
                    return {"ok": False, "detail": body.get("description", "unknown error")}
                return {"ok": True, "updates": body.get("result", [])}
        except Exception as exc:
            return {"ok": False, "detail": f"telegram api call failed: {exc}"}
