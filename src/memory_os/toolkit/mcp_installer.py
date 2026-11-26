"""One-command MCP configuration installer for Claude Code, Cursor, and Codex.

Generates or safely merges the Memory OS stdio MCP server definition without
overwriting existing MCP servers in the user's configuration file.

Usage:
    python -m memory_os.toolkit.mcp_installer --client claude --root .
    python -m memory_os.toolkit.mcp_installer --client cursor --scope global
    python -m memory_os.toolkit.mcp_installer --client codex --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

VALID_CLIENTS = ("claude", "cursor", "codex")
VALID_SCOPES = ("project", "global")


def resolve_target_path(
    client: str,
    *,
    root: Path,
    scope: str = "project",
    home_dir: Optional[Path] = None,
) -> Path:
    if client not in VALID_CLIENTS:
        raise ValueError(f"unsupported client: {client} (choose from {', '.join(VALID_CLIENTS)})")
    if scope not in VALID_SCOPES:
        raise ValueError(f"unsupported scope: {scope} (choose from {', '.join(VALID_SCOPES)})")

    home = (home_dir or Path.home()).resolve()
    root_resolved = root.resolve()

    if client == "claude":
        return (root_resolved / ".mcp.json") if scope == "project" else (home / ".claude.json")
    if client == "cursor":
        return (root_resolved / ".cursor" / "mcp.json") if scope == "project" else (home / ".cursor" / "mcp.json")
    # codex
    return (root_resolved / ".codex" / "config.toml") if scope == "project" else (home / ".codex" / "config.toml")


def build_mcp_server_entry(
    *,
    root: Path,
    python_executable: Optional[str] = None,
    server_name: str = "memory-os",
) -> Dict[str, Any]:
    py_bin = python_executable or sys.executable
    return {
        "name": server_name,
        "command": py_bin,
        "args": ["-m", "memory_os", "--root", str(root.resolve()), "mcp"],
    }


def install_mcp_config(
    *,
    client: str,
    root: Path,
    scope: str = "project",
    python_executable: Optional[str] = None,
    server_name: str = "memory-os",
    dry_run: bool = False,
    home_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    target = resolve_target_path(client, root=root, scope=scope, home_dir=home_dir)
    entry = build_mcp_server_entry(root=root, python_executable=python_executable, server_name=server_name)

    if client in {"claude", "cursor"}:
        content, action = _merge_json_mcp_config(target, entry)
    else:
        content, action = _merge_codex_toml_config(target, entry)

    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    return {
        "ok": True,
        "client": client,
        "scope": scope,
        "target": str(target),
        "action": f"dry_run:{action}" if dry_run else action,
        "server": entry,
        "preview": content,
    }


def _merge_json_mcp_config(target: Path, entry: Dict[str, Any]) -> tuple[str, str]:
    existing: Dict[str, Any] = {}
    action = "created"
    if target.is_file():
        raw = target.read_text(encoding="utf-8").strip()
        if raw:
            existing = json.loads(raw)
            if not isinstance(existing, dict):
                raise ValueError(f"existing JSON config at {target} must be a JSON object")
        action = "updated"

    servers = existing.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError(f"'mcpServers' in {target} must be a JSON object")

    servers[entry["name"]] = {
        "command": entry["command"],
        "args": entry["args"],
    }
    return json.dumps(existing, indent=2, sort_keys=True) + "\n", action


def _merge_codex_toml_config(target: Path, entry: Dict[str, Any]) -> tuple[str, str]:
    toml_key = entry["name"].replace("-", "_")
    header = f"[mcp_servers.{toml_key}]"
    args_json = json.dumps(entry["args"])
    cmd_json = json.dumps(entry["command"])
    block = f"{header}\ncommand = {cmd_json}\nargs = {args_json}\n"

    if not target.is_file():
        return block, "created"

    existing = target.read_text(encoding="utf-8")
    lines = existing.splitlines()
    start_idx: Optional[int] = None
    end_idx: int = len(lines)

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped == header:
            start_idx = idx
            continue
        if start_idx is not None and stripped.startswith("[") and stripped.endswith("]"):
            end_idx = idx
            break

    if start_idx is not None:
        new_lines = lines[:start_idx] + block.rstrip("\n").splitlines() + lines[end_idx:]
        return "\n".join(new_lines).rstrip("\n") + "\n", "updated"

    sep = "\n\n" if existing.strip() else ""
    return existing.rstrip("\n") + sep + block, "updated"


def handle_mcp_install_cli(args: argparse.Namespace, config: Any = None) -> int:
    del config
    root = Path(getattr(args, "root", ".") or ".").resolve()
    result = install_mcp_config(
        client=args.client,
        root=root,
        scope=getattr(args, "scope", "project"),
        python_executable=getattr(args, "python", None),
        dry_run=bool(getattr(args, "dry_run", False)),
    )
    if getattr(args, "format", "text") == "json":
        print(json.dumps({k: v for k, v in result.items() if k != "preview"}, indent=2))
    else:
        print(f"MCP config [{result['action']}] -> {result['target']}")
        print(f"  client={result['client']} scope={result['scope']} server={result['server']['name']}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Install Memory OS stdio MCP config for Claude Code, Cursor, or Codex.")
    parser.add_argument("--client", required=True, choices=VALID_CLIENTS)
    parser.add_argument("--root", default=".", help="Project root directory.")
    parser.add_argument("--scope", default="project", choices=VALID_SCOPES)
    parser.add_argument("--python", default=None, help="Explicit Python interpreter path.")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing files.")
    parser.add_argument("--format", choices={"text", "json"}, default="text")
    args = parser.parse_args(argv)
    return handle_mcp_install_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
