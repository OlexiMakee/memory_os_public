from memory_os.core.logger import get_logger
logger = get_logger(__name__)
import sys
from typing import Optional
from memory_os.core.interfaces import ILlmProviderService


def _call_llm_direct(user_message: str, system_prompt: str,
                     provider: Optional[str] = None, model: Optional[str] = None) -> str:
    """
    Minimal portable LLM caller using env vars + urllib.
    Supports Gemini and OpenAI-compatible APIs (OpenRouter, OpenAI).
    """
    import os
    import json

    providers_to_try = [provider] if provider else ["gemini", "openrouter", "openai"]

    for prov in providers_to_try:
        if prov == "gemini":
            api_key = os.environ.get("GEMINI_API_KEY", "")
            resolved_model = model or "gemini-2.0-flash"
            if not api_key:
                continue
            try:
                import urllib.request
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{resolved_model}:generateContent?key={api_key}"
                # systemInstruction is a separate field from contents — keeping
                # the trusted instruction structurally apart from untrusted
                # user_message (transcript text, memory summaries, etc.)
                # instead of string-concatenating them into one user message,
                # which gave injected text in user_message no structural
                # separation from the real system prompt.
                payload = {
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{"role": "user", "parts": [{"text": user_message}]}],
                }
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    result = json.loads(resp.read())
                    return result["candidates"][0]["content"]["parts"][0]["text"]
            except Exception as exc:
                logger.error(f"[DefaultLlmProviderService] gemini direct call failed: {exc}")
                continue

        elif prov in ("openrouter", "openai"):
            api_key = os.environ.get("OPENROUTER_API_KEY" if prov == "openrouter" else "OPENAI_API_KEY", "")
            base_url = "https://openrouter.ai/api/v1" if prov == "openrouter" else "https://api.openai.com/v1"
            resolved_model = model or ("google/gemini-2.0-flash-exp:free" if prov == "openrouter" else "gpt-4o-mini")
            if not api_key:
                continue
            try:
                import urllib.request
                url = f"{base_url}/chat/completions"
                payload = {
                    "model": resolved_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ]
                }
                data = json.dumps(payload).encode("utf-8")
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
                req = urllib.request.Request(url, data=data, headers=headers)
                with urllib.request.urlopen(req, timeout=60) as resp:
                    result = json.loads(resp.read())
                    return result["choices"][0]["message"]["content"]
            except Exception as exc:
                logger.error(f"[DefaultLlmProviderService] {prov} direct call failed: {exc}")
                continue

    raise RuntimeError("No LLM provider configured with valid API keys in environment.")


class DefaultLlmProviderService(ILlmProviderService):
    """
    Concrete implementation of ILlmProviderService.
    Uses a minimal stdlib + env-var HTTP caller.
    Supports GEMINI_API_KEY, OPENROUTER_API_KEY, OPENAI_API_KEY.
    """

    def call_llm(
        self,
        user_message: str,
        system_prompt: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> str:
        return _call_llm_direct(user_message, system_prompt, provider, model)
