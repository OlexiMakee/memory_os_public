"""Declarative MCP capability adapter for Memory OS.

This stage declares the least-privilege surface that Memory OS would expose via
MCP and provides a small authorization guard for future tool dispatch. It
intentionally does not run a blocking stdio server loop yet.

External content that reaches future MCP tools must be treated as untrusted
data, never as executable instruction.
"""

from __future__ import annotations

import importlib.util
from typing import Any, Dict, List, Tuple


AllowedTool = Tuple[str, bool]
DeniedTool = Tuple[str, str]


_ALLOWED_TOOLS: Tuple[AllowedTool, ...] = (
    ("search_memory", False),
    ("build_context_pack", False),
    ("read_approved_evidence", False),
    ("run_doctor", False),
    ("run_resources", False),
    ("run_security_scan", False),
    ("propose_memory_update", True),
)

_DENIED_TOOLS: Tuple[DeniedTool, ...] = (
    ("arbitrary_shell", "arbitrary command execution is outside the MCP default capability boundary"),
    ("arbitrary_filesystem_read", "filesystem access must be scoped to approved Memory OS capabilities"),
    ("destructive_graph_write", "destructive memory graph mutations require explicit human-governed workflows"),
    ("raw_telemetry_read", "raw telemetry may contain sensitive operational context and is not exposed by default"),
    ("secret_read", "secrets and credential material must never be exposed through MCP tools"),
    ("network_fetch", "network access is not part of the default local-first MCP surface"),
)


def is_available() -> bool:
    """Return True when the optional mcp package is importable."""
    return importlib.util.find_spec("mcp") is not None


def manifest() -> Dict[str, Any]:
    """Return the declared MCP capability manifest without side effects."""
    allowed: List[Dict[str, Any]] = [
        {"tool": tool, "requires_approval": requires_approval}
        for tool, requires_approval in _ALLOWED_TOOLS
    ]
    denied: List[Dict[str, Any]] = [
        {"tool": tool, "reason": reason}
        for tool, reason in _DENIED_TOOLS
    ]
    return {"allowed": allowed, "denied": denied}


def authorize_tool_call(tool_name: str, approved: bool = False) -> Dict[str, Any]:
    """Enforce the declared MCP tool policy for a single tool call."""
    denied_tools = {tool for tool, _reason in _DENIED_TOOLS}
    if tool_name in denied_tools:
        return {"ok": False, "detail": f"tool '{tool_name}' is denied"}

    allowed_tools = dict(_ALLOWED_TOOLS)
    if tool_name not in allowed_tools:
        return {"ok": False, "detail": f"unknown tool '{tool_name}'"}

    if allowed_tools[tool_name] and approved is not True:
        return {"ok": False, "detail": f"tool '{tool_name}' requires approval"}

    return {"ok": True}


def audit() -> Dict[str, Any]:
    """Return an instant, local audit of the declared MCP capability layer."""
    current_manifest = manifest()
    return {
        "available": is_available(),
        "allowed_tool_count": len(current_manifest["allowed"]),
        "denied_tool_count": len(current_manifest["denied"]),
    }


def serve(dry_run: bool = True) -> Dict[str, Any]:
    """Describe the MCP server action without starting a blocking stdio loop."""
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "detail": "would start an MCP stdio server exposing only the manifest's allowed tools",
            "manifest": manifest(),
        }

    if not is_available():
        return {"ok": False, "detail": "mcp package not installed"}

    try:
        import mcp as _mcp
    except ImportError:
        return {"ok": False, "detail": "mcp package not installed"}

    del _mcp
    return {"ok": False, "detail": "real MCP server loop not implemented in this stage"}
