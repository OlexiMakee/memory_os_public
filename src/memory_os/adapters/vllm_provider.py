"""Thin vLLM server-profile adapter using an OpenAI-compatible endpoint."""

from __future__ import annotations

import importlib.util
from typing import Any, Dict, Optional

from memory_os.core.safe_id import validate_outbound_base_url


def is_available() -> bool:
    """Return True when the OpenAI client package is importable."""
    return importlib.util.find_spec("openai") is not None


def _get_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _extract_completion_text(response: Any) -> str:
    choices = _get_value(response, "choices") or []
    if not choices:
        return ""

    first_choice = choices[0]
    message = _get_value(first_choice, "message")
    if message is not None:
        content = _get_value(message, "content")
        return "" if content is None else str(content)

    text = _get_value(first_choice, "text")
    return "" if text is None else str(text)


class VLLMProvider:
    """Adapter for an already-running vLLM OpenAI-compatible HTTP server."""

    def __init__(self, base_url: Optional[str] = None) -> None:
        validate_outbound_base_url(base_url, "vLLM base_url")
        self.base_url = base_url

    def complete(self, prompt: str, model: str = "default") -> Dict[str, Any]:
        """Complete a prompt through an explicitly configured vLLM server."""
        if self.base_url is None:
            return {"ok": False, "detail": "no vLLM server base_url configured"}

        if not is_available():
            return {"ok": False, "detail": "openai client package not installed"}

        try:
            import openai
        except ImportError:
            return {"ok": False, "detail": "openai client package not installed"}

        try:
            client = openai.OpenAI(
                api_key="EMPTY",
                base_url=self.base_url,
                timeout=5,
            )
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            return {"ok": False, "detail": f"vllm call failed: {exc}"}

        return {
            "ok": True,
            "text": _extract_completion_text(response),
            "model": model,
        }

    def audit(self) -> Dict[str, Any]:
        """Return instant availability/configuration without network I/O."""
        return {"available": is_available(), "base_url": self.base_url}
