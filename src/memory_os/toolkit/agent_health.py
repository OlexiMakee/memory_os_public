"""Agent Health Probe for checking CLI, model, and script agent health and quotas."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

from memory_os.toolkit.agent_registry import load_agent_registry
from memory_os.toolkit.console_parser import RATE_LIMIT_KEYWORDS

_HEALTH_CACHE_FILE = "agent_context/agents/health_cache.json"

_RATE_LIMIT_KEYWORDS = RATE_LIMIT_KEYWORDS


class AgentHealthProbe:
    """Probes registered agents for availability, binary presence, and rate limits."""

    def __init__(self, root: Path):
        self.root = root
        self.cache_path = self.root / _HEALTH_CACHE_FILE

    def _load_cache(self) -> Dict[str, Any]:
        if not self.cache_path.exists():
            return {}
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_cache(self, cache: Dict[str, Any]) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception as _e:
            import sys as _sys
            print(f'Ignored exception: {_e}', file=_sys.stderr)

    def verify_system_prompt(self, agent_id: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
        kind = cfg.get("kind", "")
        if kind in ("script", "shell"):
            return {"ok": True, "detail": "deterministic tool (no system prompt needed)"}

        prompt_text = cfg.get("system_prompt")
        if not prompt_text:
            prompt_file = cfg.get("system_prompt_file")
            if prompt_file:
                path = self.root / prompt_file
                if path.exists():
                    try:
                        prompt_text = path.read_text(encoding="utf-8")
                    except Exception as exc:
                        return {"ok": False, "detail": f"failed reading system_prompt_file: {exc}"}
                else:
                    return {"ok": False, "detail": f"system_prompt_file not found: {prompt_file}"}
            else:
                fallback = self.root / "agent_context" / "agents" / "prompts" / f"{agent_id}.md"
                if fallback.exists():
                    try:
                        prompt_text = fallback.read_text(encoding="utf-8")
                    except Exception as _e:
                        import sys as _sys
                        print(f'Ignored exception: {_e}', file=_sys.stderr)

        if not prompt_text:
            return {"ok": False, "detail": "no system prompt configured"}

        text_lower = prompt_text.lower()
        has_memory_os = "memory_os" in text_lower or "memory.search" in text_lower or "memory.write" in text_lower
        has_prioritization = any(kw in text_lower for kw in ["priorit", "mandatory", "first", "must", "tool"])
        if has_memory_os and has_prioritization:
            return {"ok": True, "detail": "system prompt prioritizes memory_os tools"}
        elif has_memory_os:
            return {"ok": True, "detail": "system prompt references memory_os"}
        else:
            return {"ok": False, "detail": "system prompt missing memory_os tool prioritization"}


    def check(self, agent_id: str, cfg: Optional[Dict[str, Any]] = None, ttl: int = 60, force: bool = False) -> Dict[str, Any]:
        now = time.time()
        pane_output = None
        cache = self._load_cache()
        quota_entry: Dict[str, Any] = {}
        if agent_id == "codex":
            try:
                from memory_os.toolkit.quota_harvester import refresh_quota_state
                quota_entry = refresh_quota_state(self.root).get(agent_id, {})
            except Exception:
                quota_entry = {}

        if not force and agent_id in cache:
            entry = cache[agent_id]
            usage_ts = float(quota_entry.get("usage_harvested_at", 0))
            if (
                isinstance(entry, dict)
                and (now - entry.get("ts", 0)) < ttl
                and usage_ts <= float(entry.get("ts", 0))
            ):
                return entry

        if cfg is None:
            registry = load_agent_registry(self.root)
            cfg = registry.get("agent", {}).get(agent_id)

        if not cfg:
            result = {"status": "missing_registry", "detail": f"Agent '{agent_id}' not in registry", "ts": now}
            cache[agent_id] = result
            self._save_cache(cache)
            return result

        kind = cfg.get("kind", "cli_agent")
        cmd = cfg.get("command", [])
        binary = cmd[0] if cmd else None

        if kind in ("shell", "script"):
            if binary and shutil.which(binary) is None:
                result = {"status": "missing_binary", "detail": f"Binary '{binary}' not found", "ts": now}
            else:
                result = {"status": "ok", "detail": "Available", "ts": now}

        elif kind == "local_model":
            if binary == "ollama" and shutil.which(binary) is None:
                from memory_os.core.llm_service import ollama_http_health
                health = ollama_http_health(timeout=1.5)
                if health.get("ok"):
                    result = {"status": "ok", "detail": f"ollama HTTP {health['host']} model={health['model']}", "ts": now}
                else:
                    result = {"status": "unreachable", "detail": "Ollama HTTP API unreachable", "ts": now}
            elif binary and shutil.which(binary) is None:
                result = {"status": "missing_binary", "detail": f"Binary '{binary}' not found", "ts": now}
            else:
                result = {"status": "ok", "detail": "Available", "ts": now}

        elif kind == "cli_agent":
            if not binary or shutil.which(binary) is None:
                result = {"status": "missing_binary", "detail": f"Binary '{binary}' not found in PATH", "ts": now}
            else:
                # Pane reachability, runtime-agnostic (tmux or zellij). Quota status
                # comes from harvested state, not pane scanning — the old -S -30
                # capture false-positived on our own diagnostic output.
                pane_output = None
                try:
                    from memory_os.toolkit.multiplexer_manager import MultiplexerManager
                    from memory_os.core.config import MemoryOSConfig
                    cfg_obj = MemoryOSConfig(str(self.root / "memory_os.config.json"))
                    session_name = cfg_obj.tmux_session_name

                    mgr = MultiplexerManager(self.root)
                    target_pane = mgr.resolve_pane_target(agent_id)
                    panes = mgr.list_panes(session_name)
                    if panes and not target_pane.startswith("%") and not any(
                        str(p.target) == str(target_pane) for p in panes
                    ):
                        result = {"status": "unreachable", "detail": f"Pane for agent '{agent_id}' is not active", "ts": now}
                        result["prompt"] = self.verify_system_prompt(agent_id, cfg)
                        cache[agent_id] = result
                        self._save_cache(cache)
                        return result
                    
                    try:
                        pane_output = mgr.capture_pane(target_pane, lines=100, full_history=True)
                    except Exception as _e:
                        import sys as _sys
                        print(f'Ignored exception: {_e}', file=_sys.stderr)

                    from memory_os.toolkit.agent_limits import agent_limit_active
                    if not quota_entry:
                        from memory_os.toolkit.quota_harvester import refresh_quota_state
                        quota_entry = refresh_quota_state(self.root).get(agent_id, {})
                    if agent_limit_active(state=quota_entry):
                        result = {"status": "quota_exhausted", "detail": f"Quota limit active for '{agent_id}' (harvested state)", "ts": now}
                        result["prompt"] = self.verify_system_prompt(agent_id, cfg)
                        if pane_output:
                            from memory_os.toolkit.console_parser import get_parser
                            parser = get_parser(agent_id)
                            result["console_info"] = parser.parse(agent_id, pane_output)
                            result["console_info"]["limit_event"] = parser.extract_limit_event(pane_output, strict=True)
                        cache[agent_id] = result
                        self._save_cache(cache)
                        return result
                except Exception as _e:
                    import sys as _sys
                    print(f'Ignored exception: {_e}', file=_sys.stderr)

                probe_cmd = [binary, "--version"]
                try:
                    proc = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=2.5)
                    output = (proc.stdout + "\n" + proc.stderr).lower()
                    if any(kw in output for kw in _RATE_LIMIT_KEYWORDS):
                        result = {"status": "rate_limited", "detail": "Rate limit / quota error detected in probe output", "ts": now}
                    elif proc.returncode != 0 and proc.returncode != 1:
                        result = {"status": "error", "detail": f"Probe exited with code {proc.returncode}", "ts": now}
                    else:
                        result = {"status": "ok", "detail": "Binary executable and responsive", "ts": now}
                except subprocess.TimeoutExpired:
                    result = {"status": "timeout", "detail": "Probe command timed out", "ts": now}
                except Exception as exc:
                    result = {"status": "error", "detail": str(exc), "ts": now}

                if pane_output:
                    from memory_os.toolkit.console_parser import get_parser
                    parser = get_parser(agent_id)
                    result["console_info"] = parser.parse(agent_id, pane_output)
                    result["console_info"]["limit_event"] = parser.extract_limit_event(pane_output, strict=True)

        else:
            result = {"status": "ok", "detail": f"Unknown kind '{kind}' assumed ok", "ts": now}

        result["prompt"] = self.verify_system_prompt(agent_id, cfg)
        if "result" in locals() and pane_output:
            try:
                from memory_os.toolkit.console_parser import get_parser
                parser = get_parser(agent_id)
                result["console_info"] = parser.parse(agent_id, pane_output)
                result["console_info"]["limit_event"] = parser.extract_limit_event(pane_output, strict=True)
            except Exception as _e:
                import sys as _sys
                print(f'Ignored exception: {_e}', file=_sys.stderr)
        cache[agent_id] = result
        self._save_cache(cache)
        return result



    def check_all(self, ttl: int = 60, force: bool = False) -> Dict[str, Dict[str, Any]]:
        registry = load_agent_registry(self.root)
        agents = registry.get("agent", {})
        results: Dict[str, Dict[str, Any]] = {}
        for agent_id, cfg in agents.items():
            results[agent_id] = self.check(agent_id, cfg, ttl=ttl, force=force)
        return results
