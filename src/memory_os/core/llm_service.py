from memory_os.core.logger import get_logger
logger = get_logger(__name__)
import sys
from dataclasses import dataclass
from typing import Any, Dict, Optional
from memory_os.core.interfaces import ILlmProviderService


# OpenAI-compatible cloud providers: same /chat/completions and /models
# request shape, only the base URL and key env var differ. There is no
# hardcoded "default model" here on purpose — see _discover_free_model().
_OPENAI_COMPATIBLE: dict = {
    "groq": {
        "env_key": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
    },
    "openrouter": {
        "env_key": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
    },
    "openai": {
        "env_key": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
    },
}

# Used only if live discovery fails (offline, provider outage, schema
# change) — a last-resort guess, not the source of truth for "best" model.
_LAST_RESORT_MODEL = {
    "gemini": "gemini-2.0-flash",
    "groq": "llama-3.3-70b-versatile",
    "openrouter": "google/gemini-2.0-flash-exp:free",
    "openai": "gpt-4o-mini",
}

_OLLAMA_MODEL_CACHE: Dict[str, tuple[float, Optional[str]]] = {}
_OLLAMA_MODEL_CACHE_TTL_SEC = 30.0
_LOCAL_PROVIDER_ORDER = ("llama_server", "llama_cpp", "ollama")
_CLOUD_PROVIDER_ORDER = ("gemini", "groq", "openrouter", "openai")
_PROVIDER_ORDER = _LOCAL_PROVIDER_ORDER + _CLOUD_PROVIDER_ORDER


@dataclass(frozen=True)
class _LlmCallContext:
    user_message: str
    system_prompt: str
    provider: Optional[str]
    model: Optional[str]
    response_schema: Optional[Dict[str, Any]]
    lora_role: Optional[str]
    max_tokens: int


class _ProviderAttempt:
    name: str

    def try_call(self, ctx: _LlmCallContext) -> Optional[str]:
        raise NotImplementedError


def _raw_completion_prompt(ctx: _LlmCallContext, has_lora: bool) -> str:
    raw_content = (
        ctx.system_prompt + "\n" + ctx.user_message
    ).lstrip() if ctx.system_prompt else ctx.user_message
    if not has_lora:
        return raw_content
    return (
        f"<|im_start|>user\n{raw_content}\n<|im_end|>\n"
        f"<|im_start|>assistant\n<think>\n</think>\n"
    )


def _discover_llama_cpp(lora_role: Optional[str] = None) -> Optional[tuple]:
    """Return (binary, model_path, lora_path|None).

    LLAMA_CPP_MODEL            — path to base .gguf (required)
    LLAMA_CPP_BIN              — path to llama-completion binary (optional, has default)
    LLAMA_CPP_LORA             — LoRA adapter GGUF for the default (action) role
    LLAMA_CPP_LORA_RESPONDER   — LoRA adapter GGUF for the responder role
    LLAMA_CPP_LORA_<ROLE>      — generic pattern for any future named role

    lora_role: None → LLAMA_CPP_LORA; "responder" → LLAMA_CPP_LORA_RESPONDER; etc.
    """
    import os
    import shutil
    from pathlib import Path
    model = os.environ.get("LLAMA_CPP_MODEL", "")
    if not model or not Path(model).is_file():
        return None
    binary = os.environ.get("LLAMA_CPP_BIN") or shutil.which("llama-completion") or ""
    if not binary or not Path(binary).is_file():
        return None
    lora_var = f"LLAMA_CPP_LORA_{lora_role.upper()}" if lora_role else "LLAMA_CPP_LORA"
    lora = os.environ.get(lora_var, "")
    lora_path = lora if lora and Path(lora).is_file() else None
    return (binary, model, lora_path)


def _discover_llama_server(lora_role: Optional[str] = None) -> Optional[str]:
    """Return base URL of a running llama-server instance, or None.

    LLAMA_SERVER_URL              — default server (action role)
    LLAMA_SERVER_URL_RESPONDER    — responder server (lora_role='responder')
    LLAMA_SERVER_URL_<ROLE>       — generic pattern for any future named role

    By convention: if LLAMA_SERVER_URL* is set AND the corresponding
    LLAMA_CPP_LORA* env var is also set, the server is assumed to have been
    started with that LoRA adapter (so the chat-template prompt format is used).
    """
    import os
    import urllib.request

    role_var = f"LLAMA_SERVER_URL_{lora_role.upper()}" if lora_role else None
    url = (role_var and os.environ.get(role_var, "")) or os.environ.get("LLAMA_SERVER_URL", "")
    if not url:
        return None
    url = url.rstrip("/")
    try:
        urllib.request.urlopen(f"{url}/health", timeout=1.5)
        return url
    except Exception:
        return None


def _call_llama_server(
    url: str,
    prompt: str,
    response_schema: Optional[Dict[str, Any]] = None,
    max_tokens: int = 200,
) -> str:
    """POST to llama-server /completion endpoint (raw completion, no chat-template wrapping).

    cache_prompt=True lets the server reuse KV cache for identical prefix tokens
    across requests — significant speedup when system prompt is the same across calls.
    """
    import json
    import re
    import urllib.request

    payload: Dict[str, Any] = {
        "prompt": prompt,
        "n_predict": max_tokens,
        "temperature": 0,
        "top_k": 1,
        "stream": False,
        "cache_prompt": True,
    }
    if response_schema is not None:
        payload["json_schema"] = response_schema
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/completion",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60.0) as resp:
        result = json.loads(resp.read())
    output = result.get("content", "")
    for marker in ("[end of text]", "<|endoftext|>", "<|end|>"):
        output = output.replace(marker, "")
    output = re.sub(r'.*?</think>\s*', '', output, flags=re.DOTALL)
    return output.strip()


def _call_llama_cpp(
    binary: str,
    model_path: str,
    prompt: str,
    response_schema: Optional[Dict[str, Any]] = None,
    timeout: float = 60.0,
    lora_path: Optional[str] = None,
    max_tokens: int = 200,
) -> str:
    """
    Invoke llama-completion with -no-cnv (raw completion, no chat template).
    -no-cnv is critical for Qwen3.5-4B-Base: the default cli mode injects
    a chat template and triggers <think> tokens that break JSON schema sampling.

    response_schema (a JSON Schema dict) is written to a temp file and passed
    via --json-schema-file for constrained decoding at the grammar level —
    stronger than prompt instructions alone.

    lora_path — optional path to a LoRA adapter GGUF (from convert_lora_to_gguf.py).
    When set, the adapter is loaded via --lora and applied on top of the base model.
    """
    import json
    import os
    import re
    import subprocess
    import tempfile

    cmd = [
        binary, "-m", model_path, "-no-cnv",
        "-p", prompt,
        "-n", str(max_tokens), "--temp", "0", "--top-k", "1",
        "--no-display-prompt", "--simple-io",
    ]
    if lora_path:
        cmd += ["--lora", lora_path]

    schema_file = None
    try:
        if response_schema is not None:
            fd, schema_file = tempfile.mkstemp(suffix=".json", prefix="memory_os_schema_")
            with os.fdopen(fd, "w") as fh:
                json.dump(response_schema, fh)
            cmd += ["--json-schema-file", schema_file]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            raise RuntimeError(f"llama-completion exited {result.returncode}: {result.stderr[:300]}")
        output = result.stdout  # noqa: S603 — binary path validated by _discover_llama_cpp
        # Strip EOS markers appended by llama.cpp before JSON parsing.
        for marker in ("[end of text]", "<|endoftext|>", "<|end|>"):
            output = output.replace(marker, "")
        # Strip Qwen3.5 thinking block (</think> prefix) — appears when the
        # LoRA adapter was trained with chat template that enables chain-of-thought.
        output = re.sub(r'.*?</think>\s*', '', output, flags=re.DOTALL)
        return output.strip()
    finally:
        if schema_file:
            try:
                os.unlink(schema_file)
            except Exception as _e:
                import sys as _sys
                print(f'Ignored exception: {_e}', file=_sys.stderr)


def _discover_ollama_model(host: str, timeout: float = 1.5) -> Optional[str]:
    """Ask the local Ollama daemon what's actually pulled, instead of assuming a model name."""
    import json
    import os
    import time
    import urllib.request
    explicit = os.environ.get("OLLAMA_MODEL", "").strip()
    if explicit:
        return explicit
    now = time.monotonic()
    cached = _OLLAMA_MODEL_CACHE.get(host)
    if cached and now - cached[0] < _OLLAMA_MODEL_CACHE_TTL_SEC:
        return cached[1]
    try:
        req = urllib.request.Request(f"{host}/api/tags")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        models = data.get("models", [])
        resolved = models[0]["name"] if models else None
        _OLLAMA_MODEL_CACHE[host] = (now, resolved)
        return resolved
    except Exception:
        _OLLAMA_MODEL_CACHE[host] = (now, None)
        return None


def ollama_http_health(host: Optional[str] = None, timeout: float = 1.5) -> Dict[str, Any]:
    """Return local Ollama HTTP health without requiring the `ollama` CLI.

    This is intentionally small and dependency-free because it is used by the
    agent registry/router hot path. A Dockerized Ollama bound to localhost is a
    valid local-model runtime even when the host binary is absent from PATH.
    """
    import os

    resolved_host = (host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
    model = _discover_ollama_model(resolved_host, timeout=timeout)
    return {
        "ok": bool(model),
        "host": resolved_host,
        "model": model,
        "detail": f"HTTP API reachable; model={model}" if model else "HTTP API unavailable or no models pulled",
    }


def _call_ollama(
    host: str,
    model: str,
    system_prompt: str,
    user_message: str,
    format: Optional[Dict[str, Any]] = None,
    timeout: float = 120.0,
) -> str:
    """
    `format` is Ollama's structured-output parameter: a JSON Schema dict
    (e.g. from agent_brain.grammar.JSONSchemaConstraint) constrains the
    model's output at decode time, not just via prompt instructions. Plain
    `"json"` (valid-JSON-but-unconstrained-shape) is also accepted by
    Ollama but not used here — callers that need a shape pass a schema.
    """
    import json
    import urllib.request
    url = f"{host}/api/chat"
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "stream": False,
    }
    if format is not None:
        payload["format"] = format
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read())
        return result["message"]["content"]


def _discover_free_model(base_url: str, api_key: str, prov: str, timeout: float = 8.0) -> Optional[str]:
    """
    Ask the provider's live /models endpoint what's currently free and usable,
    rather than trusting a model name baked into source code — free-tier
    catalogs get renamed/retired upstream on a timeline we don't control.
    """
    import json
    import urllib.request
    try:
        req = urllib.request.Request(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        models = data.get("data", [])
    except Exception:
        return None

    if prov == "openrouter":
        def _is_free(m: dict) -> bool:
            if str(m.get("id", "")).endswith(":free"):
                return True
            pricing = m.get("pricing") or {}
            try:
                return float(pricing.get("prompt", 1)) == 0.0 and float(pricing.get("completion", 1)) == 0.0
            except (TypeError, ValueError):
                return False

        free = [m for m in models if _is_free(m)]
        if not free:
            return None
        free.sort(key=lambda m: m.get("context_length") or 0, reverse=True)
        return free[0]["id"]

    if prov == "groq":
        pool = [m for m in models if m.get("active", True)] or models
        if not pool:
            return None
        pool.sort(key=lambda m: m.get("context_window") or 0, reverse=True)
        return pool[0]["id"]

    return None


def _discover_gemini_model(api_key: str, timeout: float = 8.0) -> Optional[str]:
    """Pick a current Gemini Flash-tier model from the live ListModels catalog."""
    import json
    import urllib.request
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read())
        models = data.get("models", [])
    except Exception:
        return None

    candidates = [
        m for m in models
        if "generateContent" in m.get("supportedGenerationMethods", [])
        and "flash" in m.get("name", "")
        and "exp" not in m.get("name", "")
    ]
    if not candidates:
        return None
    # Names look like "models/gemini-2.5-flash" — newest version sorts last.
    candidates.sort(key=lambda m: m.get("name", ""))
    return candidates[-1]["name"].split("/")[-1]


class _LlamaServerProvider(_ProviderAttempt):
    name = "llama_server"

    def try_call(self, ctx: _LlmCallContext) -> Optional[str]:
        import os

        url = _discover_llama_server(lora_role=ctx.lora_role)
        if not url:
            return None
        lora_var = f"LLAMA_CPP_LORA_{ctx.lora_role.upper()}" if ctx.lora_role else "LLAMA_CPP_LORA"
        full_prompt = _raw_completion_prompt(ctx, has_lora=bool(os.environ.get(lora_var, "")))
        try:
            return _call_llama_server(url, full_prompt, ctx.response_schema, ctx.max_tokens)
        except Exception as exc:
            logger.error(f"[DefaultLlmProviderService] llama_server call failed: {exc}")
            return None


class _LlamaCppProvider(_ProviderAttempt):
    name = "llama_cpp"

    def try_call(self, ctx: _LlmCallContext) -> Optional[str]:
        discovered = _discover_llama_cpp(lora_role=ctx.lora_role)
        if not discovered:
            return None
        binary, model_path, lora_path = discovered
        full_prompt = _raw_completion_prompt(ctx, has_lora=bool(lora_path))
        try:
            return _call_llama_cpp(
                binary,
                model_path,
                full_prompt,
                ctx.response_schema,
                lora_path=lora_path,
                max_tokens=ctx.max_tokens,
            )
        except Exception as exc:
            logger.error(f"[DefaultLlmProviderService] llama_cpp call failed: {exc}")
            return None


class _OllamaProvider(_ProviderAttempt):
    name = "ollama"

    def try_call(self, ctx: _LlmCallContext) -> Optional[str]:
        import os

        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        resolved_model = ctx.model or _discover_ollama_model(host)
        if not resolved_model:
            return None
        try:
            return _call_ollama(
                host,
                resolved_model,
                ctx.system_prompt,
                ctx.user_message,
                format=ctx.response_schema,
            )
        except Exception as exc:
            logger.error(f"[DefaultLlmProviderService] ollama direct call failed: {exc}")
            return None


class _GeminiProvider(_ProviderAttempt):
    name = "gemini"

    def try_call(self, ctx: _LlmCallContext) -> Optional[str]:
        import os

        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            return None
        resolved_model = ctx.model or _discover_gemini_model(api_key) or _LAST_RESORT_MODEL["gemini"]
        try:
            import json
            import urllib.request

            url = f"https://generativelanguage.googleapis.com/v1beta/models/{resolved_model}:generateContent?key={api_key}"
            payload = {
                "systemInstruction": {"parts": [{"text": ctx.system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": ctx.user_message}]}],
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read())
                return result["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as exc:
            logger.error(f"[DefaultLlmProviderService] gemini direct call failed: {exc}")
            return None


class _OpenAICompatibleProvider(_ProviderAttempt):
    def __init__(self, name: str):
        self.name = name

    def try_call(self, ctx: _LlmCallContext) -> Optional[str]:
        import os

        cfg = _OPENAI_COMPATIBLE[self.name]
        api_key = os.environ.get(cfg["env_key"], "")
        if not api_key:
            return None
        resolved_model = (
            ctx.model
            or _discover_free_model(cfg["base_url"], api_key, self.name)
            or _LAST_RESORT_MODEL[self.name]
        )
        try:
            import json
            import urllib.request

            url = f"{cfg['base_url']}/chat/completions"
            payload = {
                "model": resolved_model,
                "messages": [
                    {"role": "system", "content": ctx.system_prompt},
                    {"role": "user", "content": ctx.user_message},
                ]
            }
            data = json.dumps(payload).encode("utf-8")
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read())
                return result["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.error(f"[DefaultLlmProviderService] {self.name} direct call failed: {exc}")
            return None


def _provider_chain(provider: Optional[str] = None) -> list[_ProviderAttempt]:
    providers = [provider] if provider else list(_PROVIDER_ORDER)
    chain: list[_ProviderAttempt] = []
    for prov in providers:
        if prov == "llama_server":
            chain.append(_LlamaServerProvider())
        elif prov == "llama_cpp":
            chain.append(_LlamaCppProvider())
        elif prov == "ollama":
            chain.append(_OllamaProvider())
        elif prov == "gemini":
            chain.append(_GeminiProvider())
        elif prov in _OPENAI_COMPATIBLE:
            chain.append(_OpenAICompatibleProvider(prov))
    return chain


def _call_llm_direct(user_message: str, system_prompt: str,
                     provider: Optional[str] = None, model: Optional[str] = None,
                     response_schema: Optional[Dict[str, Any]] = None,
                     lora_role: Optional[str] = None,
                     max_tokens: Optional[int] = None) -> str:
    """
    Local-first LLM caller using env vars + urllib, no required dependencies.

    Provider order: llama_server (running HTTP server — fastest, no cold start)
    → llama_cpp (subprocess spawn) → ollama → gemini → groq → openrouter → openai.

    max_tokens: auto-derived from lora_role if None (400 for responder, 200 otherwise).
    llama_server and llama_cpp both honor this; cloud providers do not (they have
    their own defaults).
    """
    if max_tokens is None:
        max_tokens = 400 if lora_role == "responder" else 200

    ctx = _LlmCallContext(
        user_message=user_message,
        system_prompt=system_prompt,
        provider=provider,
        model=model,
        response_schema=response_schema,
        lora_role=lora_role,
        max_tokens=max_tokens,
    )

    for provider_attempt in _provider_chain(provider):
        result = provider_attempt.try_call(ctx)
        if result is not None:
            return result

    raise RuntimeError("No LLM provider configured with valid API keys in environment.")


class DefaultLlmProviderService(ILlmProviderService):
    """
    Concrete implementation of ILlmProviderService.
    Uses a minimal stdlib + env-var HTTP caller.
    Tries local llama-server, llama.cpp, Ollama, then GEMINI_API_KEY,
    GROQ_API_KEY, OPENROUTER_API_KEY, OPENAI_API_KEY in that order.
    """

    def call_llm(
        self,
        user_message: str,
        system_prompt: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        response_schema: Optional[Dict[str, Any]] = None,
        lora_role: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        return _call_llm_direct(user_message, system_prompt, provider, model, response_schema, lora_role, max_tokens)
