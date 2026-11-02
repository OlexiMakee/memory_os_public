from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ActionSpec:
    """
    Declares one callable action: its name, what it does, and the JSON
    shape its arguments take. This is the project's action vocabulary —
    the surface an ActionBrain is trained to emit and an ActionExecutor
    knows how to run. Deliberately mirrors memory_os's own existing tool
    surface (search/propose/read) instead of inventing a parallel one.
    """

    name: str  # dotted, e.g. "memory.search", "memory.write", "file.read"
    description: str
    args_schema: Dict[str, str]  # {"arg_name": "type hint string"}, for the prompt block only
    risk: str = "low"  # "low" | "write" | "destructive" — Orchestrator/executors may gate on this


@dataclass
class ActionRequest:
    """
    What an ActionBrain emits for one task: one action call, nothing else —
    no prose, no hedging, no explanation. Training a base model on exactly
    this shape (see docs/encyclopedia/agent_brain.md) only works if this is
    *all* it ever produces.
    """

    action: str
    args: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionResult:
    """What an ActionExecutor returns after actually running one ActionRequest."""

    action: str
    ok: bool
    data: Any = None
    error: Optional[str] = None
    action_args: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "ok": self.ok,
            "data": self.data,
            "error": self.error,
            "action_args": self.action_args,
        }
