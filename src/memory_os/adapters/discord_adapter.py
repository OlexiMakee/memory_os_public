"""
Optional adapter for the Discord Bot REST API (https://discord.com/developers/docs).

No extra dependencies — uses stdlib urllib.request. Set DISCORD_BOT_TOKEN in .env.

Security rules:
- Token is never logged, printed, or included in audit() output.
- parse_event() is pure data parsing — no network, no side effects.
- Only the REST API is used here. The Gateway (WebSocket) is NOT implemented;
  gateway mode requires a persistent async event loop and belongs in a daemon layer.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional


_BASE = "https://discord.com/api/v10"


def is_available() -> bool:
    """Always True: only stdlib is required."""
    return True


class DiscordAdapter:
    """Thin wrapper around the Discord Bot REST API.

    Supports:
    - send_message(channel_id, text) — send a text message to a channel.
    - parse_event(payload) — pure parsing of a Gateway dispatch payload.
    - audit() — offline availability check (no network, no token in output).

    Gateway (WebSocket) / intents setup must be handled at the daemon level;
    this adapter only covers REST calls and webhook payload parsing.
    """

    def __init__(self, token: Optional[str] = None, timeout: float = 10.0) -> None:
        self._token = token or os.environ.get("DISCORD_BOT_TOKEN", "")
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def send_message(
        self,
        channel_id,
        text: str,
    ) -> Dict[str, Any]:
        """Send a text message to a Discord channel.

        Args:
            channel_id: Discord channel snowflake ID (int or str).
            text: Message content (max 2000 chars per Discord limits).

        Returns:
            {"ok": True, "message_id": str} on success.
            {"ok": False, "detail": str} on any error.
        """
        if not self._token:
            return {"ok": False, "detail": "DISCORD_BOT_TOKEN not set"}
        if not text or not str(text).strip():
            return {"ok": False, "detail": "text must not be empty"}

        payload = {"content": str(text)[:2000]}
        result = self._post(f"/channels/{channel_id}/messages", payload)
        if result.get("ok") and "id" in result:
            return {"ok": True, "message_id": result["id"]}
        return result

    def send_reply(
        self,
        channel_id,
        message_id,
        text: str,
    ) -> Dict[str, Any]:
        """Send a threaded reply to an existing message.

        Args:
            channel_id: Channel snowflake ID.
            message_id: Message snowflake ID to reply to.
            text: Reply content (max 2000 chars).

        Returns:
            {"ok": True, "message_id": str} or {"ok": False, "detail": str}.
        """
        if not self._token:
            return {"ok": False, "detail": "DISCORD_BOT_TOKEN not set"}
        if not text or not str(text).strip():
            return {"ok": False, "detail": "text must not be empty"}

        payload = {
            "content": str(text)[:2000],
            "message_reference": {"message_id": str(message_id)},
        }
        result = self._post(f"/channels/{channel_id}/messages", payload)
        if result.get("ok") and "id" in result:
            return {"ok": True, "message_id": result["id"]}
        return result

    def get_channel(self, channel_id) -> Dict[str, Any]:
        """Fetch channel metadata (name, type, guild_id).

        Returns:
            {"ok": True, "id": str, "name": str, "type": int, "guild_id": str | None}
            or {"ok": False, "detail": str}.
        """
        if not self._token:
            return {"ok": False, "detail": "DISCORD_BOT_TOKEN not set"}
        return self._get(f"/channels/{channel_id}")

    def parse_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Parse a raw Discord Gateway dispatch event into a normalized dict.

        Pure function — no network, no side effects. Handles MESSAGE_CREATE and
        MESSAGE_UPDATE events; passes through others with event_type set.

        Returns:
        {
            "platform": "discord",
            "event_type": str,         # e.g. "MESSAGE_CREATE"
            "message_id": str | None,
            "channel_id": str | None,
            "guild_id": str | None,
            "user_id": str | None,
            "username": str | None,
            "text": str | None,
            "is_bot": bool,
            "raw": dict
        }
        """
        try:
            event_type = payload.get("t") or payload.get("type", "UNKNOWN")
            data = payload.get("d") or payload

            author = data.get("author") or {}
            member = data.get("member") or {}
            nick = member.get("nick")

            return {
                "platform": "discord",
                "event_type": event_type,
                "message_id": data.get("id"),
                "channel_id": data.get("channel_id"),
                "guild_id": data.get("guild_id"),
                "user_id": author.get("id"),
                "username": nick or author.get("global_name") or author.get("username"),
                "text": data.get("content"),
                "is_bot": bool(author.get("bot", False)),
                "raw": payload,
            }
        except Exception as exc:
            return {
                "platform": "discord",
                "event_type": "UNKNOWN",
                "message_id": None,
                "channel_id": None,
                "guild_id": None,
                "user_id": None,
                "username": None,
                "text": None,
                "is_bot": False,
                "raw": payload,
                "parse_error": str(exc),
            }

    def audit(self) -> Dict[str, Any]:
        """Offline availability report — no network call, token value never exposed."""
        return {
            "available": True,
            "token_configured": bool(self._token),
            "rest_api_base": _BASE,
            "note": "install: no extra package needed (stdlib urllib only). Gateway/intents need discord.py.",
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bot {self._token}",
            "Content-Type": "application/json",
        }

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{_BASE}{path}"
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = json.loads(resp.read().decode())
                return {"ok": True, **body}
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode())
                return {
                    "ok": False,
                    "detail": body.get("message", str(exc)),
                    "code": body.get("code"),
                }
            except Exception:
                return {"ok": False, "detail": str(exc)}
        except Exception as exc:
            return {"ok": False, "detail": f"discord api call failed: {exc}"}

    def _get(self, path: str) -> Dict[str, Any]:
        url = f"{_BASE}{path}"
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = json.loads(resp.read().decode())
                return {"ok": True, **body}
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode())
                return {"ok": False, "detail": body.get("message", str(exc))}
            except Exception:
                return {"ok": False, "detail": str(exc)}
        except Exception as exc:
            return {"ok": False, "detail": f"discord api call failed: {exc}"}
