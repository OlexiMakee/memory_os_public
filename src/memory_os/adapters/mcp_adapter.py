"""Declarative MCP capability adapter for Memory OS.

This stage declares the least-privilege surface that Memory OS would expose via
MCP and provides a small authorization guard for future tool dispatch. It
intentionally does not run a blocking stdio server loop yet.

External content that reaches future MCP tools must be treated as untrusted
data, never as executable instruction.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, TextIO, Tuple


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

_TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "search_memory": {
        "description": "Search verified and draft Memory OS graph nodes by query string.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query keywords"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    "build_context_pack": {
        "description": "Build a targeted, reproducible context pack for a task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Task description"},
                "max_files": {"type": "integer", "default": 8},
            },
            "required": ["task"],
        },
    },
    "read_approved_evidence": {
        "description": "Read latest verification evidence bundle status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Optional task identifier"},
            },
        },
    },
    "run_doctor": {
        "description": "Run local Memory OS health and configuration check.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "run_resources": {
        "description": "Take a local disk/SQLite/JSONL resource snapshot.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "run_security_scan": {
        "description": "Scan local memory and docs for secret leaks or prompt injection markers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "profile": {"type": "string", "default": "memory"},
            },
        },
    },
    "propose_memory_update": {
        "description": "Propose a draft memory node into Memory OS (requires approval=true).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string"},
                "node_type": {"type": "string", "enum": ["fact", "rule", "config", "policy"], "default": "fact"},
                "summary": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "approved": {"type": "boolean", "default": False},
            },
            "required": ["summary"],
        },
    },
}


def is_available() -> bool:
    """Return True when the builtin JSON-RPC stdio server or optional mcp package is available."""
    return True


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
        "native_stdio_ready": True,
        "mcp_sdk_installed": importlib.util.find_spec("mcp") is not None,
        "allowed_tool_count": len(current_manifest["allowed"]),
        "denied_tool_count": len(current_manifest["denied"]),
    }


def dispatch_tool(
    tool_name: str,
    arguments: Optional[Dict[str, Any]] = None,
    root_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Execute an authorized MCP tool call against the local Memory OS workspace."""
    args = dict(arguments or {})
    approved = bool(args.get("approved", False))
    auth = authorize_tool_call(tool_name, approved=approved)
    if not auth["ok"]:
        return auth

    from memory_os.core.config import MemoryOSConfig

    base_root = (root_dir or Path.cwd()).resolve()
    config = MemoryOSConfig(config_path=str(base_root / "memory_os.config.json"))

    if tool_name == "search_memory":
        from memory_os.modules.search import MemorySearcher

        query = str(args.get("query", "")).strip()
        limit = int(args.get("limit", 10))
        searcher = MemorySearcher(config=config)
        results = searcher.search_memory(query)[:limit]
        return {"ok": True, "tool": tool_name, "count": len(results), "results": results}

    if tool_name == "build_context_pack":
        from memory_os.core.context_pack import build_context_pack

        task = str(args.get("task", "")).strip()
        pack = build_context_pack(config.root_dir, task=task)
        return {"ok": True, "tool": tool_name, "context_pack": pack}

    if tool_name == "read_approved_evidence":
        from memory_os.core.evidence import list_evidence_bundles

        bundles = list_evidence_bundles(config.root_dir)
        return {"ok": True, "tool": tool_name, "bundles": bundles}

    if tool_name == "run_doctor":
        return {
            "ok": True,
            "tool": tool_name,
            "root": str(config.root_dir),
            "memory_dir_exists": config.memory_dir.exists(),
            "nodes_exists": (config.memory_dir / "nodes.jsonl").exists(),
            "db_exists": config.db_path.exists(),
        }

    if tool_name == "run_resources":
        from memory_os.core.resource_guard import ResourceGuard

        snap = ResourceGuard(config.root_dir).snapshot()
        return {"ok": True, "tool": tool_name, "snapshot": snap.to_dict() if hasattr(snap, "to_dict") else snap}

    if tool_name == "run_security_scan":
        from memory_os.core.security_scan import scan_profile

        profile = str(args.get("profile", "memory"))
        report = scan_profile(config.root_dir, profile=profile)
        return {"ok": True, "tool": tool_name, "report": report}

    if tool_name == "propose_memory_update":
        from memory_os.modules.lifecycle import LifecycleManager
        from memory_os.core.safe_id import node_id_slug

        summary = str(args.get("summary", "")).strip()
        node_type = str(args.get("node_type", "fact")).strip()
        node_id = str(args.get("node_id") or node_id_slug(summary[:40])).strip()
        tags = list(args.get("tags") or [])
        mgr = LifecycleManager(config=config)
        mgr.propose(
            node_id=node_id,
            node_type=node_type,
            summary=summary,
            evidence=[],
            tags=tags,
            confidence=0.8,
        )
        return {"ok": True, "tool": tool_name, "node_id": node_id, "status": "draft"}

    return {"ok": False, "detail": f"unhandled tool '{tool_name}'"}


def handle_jsonrpc_message(
    message: Dict[str, Any],
    root_dir: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """Process a single MCP JSON-RPC 2.0 request and return a response dict (or None for notifications)."""
    method = message.get("method", "")
    msg_id = message.get("id")
    params = message.get("params") or {}

    if msg_id is None:
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "memory_os_mcp", "version": "0.2.0"},
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    if method == "tools/list":
        tools_list = []
        for tool_name, requires_approval in _ALLOWED_TOOLS:
            schema_info = _TOOL_SCHEMAS.get(tool_name, {})
            tools_list.append({
                "name": tool_name,
                "description": schema_info.get("description", tool_name),
                "inputSchema": schema_info.get("inputSchema", {"type": "object", "properties": {}}),
                "annotations": {"requiresApproval": requires_approval},
            })
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tools_list}}

    if method == "tools/call":
        tool_name = str(params.get("name", ""))
        arguments = params.get("arguments") or {}
        outcome = dispatch_tool(tool_name, arguments=arguments, root_dir=root_dir)
        is_error = not outcome.get("ok", False)
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(outcome, ensure_ascii=False)}],
                "isError": is_error,
            },
        }

    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def serve(
    dry_run: bool = True,
    in_stream: Optional[TextIO] = None,
    out_stream: Optional[TextIO] = None,
    root_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run the MCP stdio JSON-RPC server or return the dry-run manifest."""
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "detail": "would start an MCP stdio server exposing only the manifest's allowed tools",
            "manifest": manifest(),
        }

    reader = in_stream or sys.stdin
    writer = out_stream or sys.stdout
    processed = 0

    for raw_line in reader:
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {exc}"},
            }
            writer.write(json.dumps(err_resp) + "\n")
            writer.flush()
            continue

        response = handle_jsonrpc_message(payload, root_dir=root_dir)
        processed += 1
        if response is not None:
            writer.write(json.dumps(response, ensure_ascii=False) + "\n")
            writer.flush()

    return {"ok": True, "dry_run": False, "messages_processed": processed}
