"""Lazy LiteLLM bridge for RuntimeDecision-style routing outputs."""

import importlib.util
from typing import Any, Dict


def is_available() -> bool:
    return importlib.util.find_spec("litellm") is not None


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


class LiteLLMAdapter:
    def complete(self, decision: Any, prompt: str) -> Dict[str, Any]:
        if not is_available():
            return {"ok": False, "detail": "litellm package not installed"}

        if decision is None:
            return {"ok": False, "detail": "decision is None"}

        try:
            provider = decision.provider
            model = decision.model
            _reason = decision.reason
        except AttributeError as exc:
            return {"ok": False, "detail": f"decision is missing a required attribute: {exc}"}

        try:
            import litellm
        except ImportError:
            return {"ok": False, "detail": "litellm package not installed"}

        try:
            response = litellm.completion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            return {"ok": False, "detail": f"litellm call failed: {exc}"}

        return {
            "ok": True,
            "text": _extract_completion_text(response),
            "model": model,
            "provider": provider,
        }

    def audit(self) -> Dict[str, Any]:
        return {"available": is_available()}
