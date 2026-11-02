"""Phase 3 — Agentic OS Router Plan.

Produces an execution plan for a task, selecting the optimal agent and mode
based on task risk, required capabilities, and agent registry availability.
Deterministic — no LLM required.

Usage:
    plan = RouterPlan(root).route(task_id="task_abc123")
    plan = RouterPlan(root).route(text="classify this message", risk="low")
    memory_os plan --task-id <id>
    memory_os plan --text "..." --risk low
"""

from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Capability → agent kind preference (ordered, first match wins)
# ---------------------------------------------------------------------------
_CAP_PREFERENCE: List[tuple] = [
    # Capability substring       Preferred kind            Fallback kind
    ("memory.search",           "script",                 "local_model"),
    ("memory.write",            "script",                 "local_model"),
    ("eval.run",                "script",                 None),
    ("audit",                   "script",                 None),
    ("snapshot",                "script",                 None),
    ("run_tests",               "shell",                  "script"),
    ("lint",                    "shell",                  "script"),
    ("git",                     "shell",                  "script"),
    ("file_ops",                "shell",                  "script"),
    ("classify",                "local_model",            "script"),
    ("tool_intent",             "local_model",            "script"),
    ("action_routing",          "local_model",            "script"),
    ("summarize_output",        "local_model",            "script"),
    ("respond",                 "local_model",            None),
    ("ukrainian_response",      "local_model",            None),
    ("summarize",               "local_model",            "script"),
    ("code_edit",               "cli_agent",              None),
    ("architecture",            "cli_agent",              None),
    ("deep_context",            "cli_agent",              None),
    ("review",                  "cli_agent",              "local_model"),
    ("repo_analysis",           "cli_agent",              "local_model"),
    ("tests",                   "cli_agent",              "shell"),
]

_RISK_REQUIRES_REVIEW = {"high"}
_LOCAL_KINDS = {"script", "shell", "local_model"}
_CLI_REQUIRED_CAPABILITIES = {"code_edit", "architecture", "deep_context", "repro_analysis"}


def _ollama_http_available() -> bool:
    try:
        from memory_os.core.llm_service import ollama_http_health
        return bool(ollama_http_health(timeout=0.5).get("ok"))
    except Exception:
        return False


@dataclass
class ExecutionPlan:
    task_id: Optional[str]
    text: str
    agent: str
    agent_kind: str
    mode: str
    capabilities_matched: List[str]
    fallback: Optional[str]
    requires_review: bool
    estimated_cost: str          # "zero", "cheap", "limited"
    rationale: str
    budget_degraded: bool        # True if downgraded due to budget exhaustion
    blocked_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RouterPlan:
    def __init__(self, root: Path):
        self.root = root
        self._registry: Optional[Dict[str, Any]] = None

    def _available_agents(self) -> List[Dict[str, Any]]:
        """Return agents whose CLI binary is present in PATH and healthy (not rate limited or unreachable)."""
        from memory_os.toolkit.agent_health import AgentHealthProbe
        from memory_os.toolkit.agent_registry import load_agent_registry

        probe = AgentHealthProbe(self.root)
        if self._registry is None:
            self._registry = load_agent_registry(self.root).get("agent", {})
        registry = self._registry
        available = []
        for agent_id, cfg in registry.items():
            health = probe.check(agent_id, cfg=cfg, ttl=60)
            if health.get("status") in ("rate_limited", "quota_exhausted", "missing_binary", "unreachable", "error"):
                continue
            cmd = cfg.get("command", [])
            binary = cmd[0] if cmd else None
            if cfg.get("kind") == "local_model" and binary == "ollama" and health.get("status") == "ok":
                available.append({"id": agent_id, **cfg, "runtime": "ollama_http"})
            else:
                available.append({"id": agent_id, **cfg})
        return available


    def _pick_agent(
        self,
        required_caps: List[str],
        risk: str,
        budget_exhausted: bool,
    ) -> tuple[Optional[Dict], Optional[Dict]]:
        """Return (primary_agent, fallback_agent) from the available registry."""
        available = self._available_agents()
        if not available:
            return None, None

        def _agents_by_kind(kind: str) -> List[Dict]:
            return [a for a in available if a.get("kind") == kind]

        def _first_capable(kind: str, caps: List[str]) -> Optional[Dict]:
            candidates = _agents_by_kind(kind)
            for a in candidates:
                a_caps = a.get("capabilities", [])
                if any(rc in ac for rc in caps for ac in a_caps):
                    return a
            # If no capability match, return first of that kind anyway
            return candidates[0] if candidates else None

        # If budget exhausted, downgrade to local-only
        if budget_exhausted:
            for kind in ("script", "shell", "local_model"):
                agent = _first_capable(kind, required_caps)
                if agent:
                    return agent, None
            return available[0] if available else None, None

        # High risk → prefer cli_agent, require human review
        if risk == "high":
            primary = _first_capable("cli_agent", required_caps)
            fallback = _first_capable("local_model", required_caps)
            return primary or fallback, fallback

        # Determine preferred kind from capability map
        preferred_kind = None
        fallback_kind = None
        matched_caps = required_caps[:1] if required_caps else []
        for cap_prefix, p_kind, f_kind in _CAP_PREFERENCE:
            if any(cap_prefix in rc for rc in required_caps):
                preferred_kind = p_kind
                fallback_kind = f_kind
                matched_caps = [rc for rc in required_caps if cap_prefix in rc]
                break

        if preferred_kind is None:
            # Default: risk=low → local, risk=medium → local with cli_agent fallback
            preferred_kind = "local_model" if risk == "low" else "cli_agent"
            fallback_kind = "cli_agent" if risk == "low" else "local_model"

        primary = _first_capable(preferred_kind, required_caps)
        fallback = _first_capable(fallback_kind, required_caps) if fallback_kind else None
        if fallback and fallback.get("id") == (primary or {}).get("id"):
            fallback = None
        return primary, fallback

    # ------------------------------------------------------------------ #
    # Public API                                                            #
    # ------------------------------------------------------------------ #

    def route(
        self,
        task_id: Optional[str] = None,
        text: str = "",
        risk: str = "low",
        capabilities: Optional[List[str]] = None,
    ) -> ExecutionPlan:
        """Produce an execution plan for the given task or free text."""
        from memory_os.toolkit.task_kernel import TaskKernel

        # Load from Task Kernel if task_id given
        task_text = text
        task_risk = risk
        task_caps = capabilities or []
        if task_id:
            kernel = TaskKernel(self.root)
            task = kernel.get(task_id)
            if task is None:
                raise KeyError(f"Task not found: {task_id}")
            task_text = task.get("goal") or task.get("title") or ""
            task_risk = task.get("risk", "low")
            task_caps = task.get("capabilities", [])

        # Check budget
        budget_exhausted = False
        try:
            from memory_os.core.routing_policy import RoutingPolicy
            from memory_os.core.config import MemoryOSConfig
            cfg_path = self.root / "memory_os.config.json"
            if cfg_path.exists():
                status = RoutingPolicy(MemoryOSConfig(str(cfg_path))).budget_status()
                budget_exhausted = status.get("exhausted", False)
        except Exception as _e:
            import sys as _sys
            print(f'Ignored exception: {_e}', file=_sys.stderr)

        primary, fallback = self._pick_agent(task_caps, task_risk, budget_exhausted)

        cli_required = sorted(
            capability
            for capability in task_caps
            if any(required in capability for required in _CLI_REQUIRED_CAPABILITIES)
        )
        if cli_required and (primary is None or primary.get("kind") != "cli_agent"):
            reason = (
                "No available cli_agent for required capabilities: "
                + ", ".join(cli_required)
            )
            return ExecutionPlan(
                task_id=task_id,
                text=task_text,
                agent="unavailable",
                agent_kind="unavailable",
                mode="blocked",
                capabilities_matched=task_caps,
                fallback=None,
                requires_review=task_risk in _RISK_REQUIRES_REVIEW,
                estimated_cost="zero",
                rationale=reason,
                budget_degraded=budget_exhausted,
                blocked_reason=reason,
            )

        # If ideal kind unavailable, promote fallback to primary
        if primary is None and fallback is not None:
            primary = fallback
            fallback = None

        if primary is None:
            # Truly no agents — absolute last resort
            return ExecutionPlan(
                task_id=task_id,
                text=task_text,
                agent="memory-os-cli",
                agent_kind="script",
                mode="local_prep",
                capabilities_matched=[],
                fallback=None,
                requires_review=True,
                estimated_cost="zero",
                rationale="No agents configured in registry — local preparation only.",
                budget_degraded=budget_exhausted,
            )

        # Determine mode from agent kind
        kind = primary.get("kind", "script")
        if kind == "local_model":
            mode = "tool_intent" if "classify" in " ".join(task_caps) else "respond"
        elif kind in ("script", "shell"):
            mode = "deterministic"
        else:
            mode = "code_edit" if "code_edit" in task_caps else "agentic"

        # Cost class
        cost_map = {"zero": "zero", "cheap": "cheap", "limited": "limited"}
        estimated_cost = cost_map.get(primary.get("cost_class", "limited"), "limited")

        requires_review = task_risk in _RISK_REQUIRES_REVIEW

        rationale_parts = [
            f"risk={task_risk}",
            f"caps={task_caps or ['(none)']}",
            f"budget_exhausted={budget_exhausted}",
            f"→ selected {primary['id']} (kind={kind}, cost={estimated_cost})",
        ]
        if fallback:
            rationale_parts.append(f"fallback={fallback['id']}")
        if requires_review:
            rationale_parts.append("requires human review (risk=high)")
        if budget_exhausted:
            rationale_parts.append("DEGRADED: big agents bypassed due to budget exhaustion")

        return ExecutionPlan(
            task_id=task_id,
            text=task_text,
            agent=primary["id"],
            agent_kind=kind,
            mode=mode,
            capabilities_matched=task_caps,
            fallback=fallback["id"] if fallback else None,
            requires_review=requires_review,
            estimated_cost=estimated_cost,
            rationale=" | ".join(rationale_parts),
            budget_degraded=budget_exhausted,
        )
