"""Workspace Registry Manager for Memory OS.

Manages ~/.memory_os/workspaces.toml for global tracking, switching,
and management of project workspaces.
"""

import hashlib
import re
from pathlib import Path
from typing import Dict, List, Any, Optional

from memory_os.core.toml_compat import load_toml_path


REGISTRY_DIR = Path.home() / ".memory_os"
REGISTRY_FILE = REGISTRY_DIR / "workspaces.toml"


def load_workspace_registry() -> Dict[str, Any]:
    """Load registry data from ~/.memory_os/workspaces.toml."""
    if not REGISTRY_FILE.exists():
        return {"workspace": {}}
    try:
        data = load_toml_path(REGISTRY_FILE)
        if "workspace" not in data:
            data["workspace"] = {}
        return data
    except Exception:
        return {"workspace": {}}


def _toml_escape(val: str) -> str:
    """Escape string values for safe inline TOML writing."""
    return val.replace("\\", "\\\\").replace('"', '\\"')


def _slugify(raw_name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", raw_name.lower()).strip("_") or "workspace"


def save_workspace_registry(data: Dict[str, Any]) -> None:
    """Save registry data to ~/.memory_os/workspaces.toml in TOML format."""
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    lines: List[str] = ["# Memory OS Workspaces Registry\n"]
    
    workspaces = data.get("workspace", {})
    for slug, info in sorted(workspaces.items()):
        clean_name = _toml_escape(str(info.get("name", slug)))
        clean_path = _toml_escape(str(info.get("path", "")))
        lines.append(f"[workspace.{slug}]")
        lines.append(f'name = "{clean_name}"')
        lines.append(f'path = "{clean_path}"')
        if "last_accessed" in info:
            lines.append(f'last_accessed = "{info["last_accessed"]}"')
        lines.append("")

    REGISTRY_FILE.write_text("\n".join(lines), encoding="utf-8")


def register_workspace(path: Path, name: Optional[str] = None) -> str:
    """Register or update a workspace path in the registry."""
    path = path.resolve()
    raw_name = name or path.name
    base_slug = _slugify(raw_name)
    
    data = load_workspace_registry()
    workspaces = data.get("workspace", {})
    
    # Check if slug exists for a DIFFERENT path -> disambiguate with path hash
    target_slug = base_slug
    if target_slug in workspaces:
        existing_path = workspaces[target_slug].get("path")
        if existing_path and str(path) != existing_path:
            path_hash = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:6]
            target_slug = f"{base_slug}_{path_hash}"

    from datetime import datetime, timezone
    now_str = datetime.now(timezone.utc).isoformat()

    workspaces[target_slug] = {
        "name": name or path.name,
        "path": str(path),
        "last_accessed": now_str,
    }
    data["workspace"] = workspaces
    save_workspace_registry(data)
    return target_slug


def unregister_workspace(name_or_path: str) -> bool:
    """Remove a workspace from the registry by slug name or path."""
    data = load_workspace_registry()
    workspaces = data.get("workspace", {})
    target_slug = None

    for slug, info in workspaces.items():
        if slug == name_or_path or info.get("name") == name_or_path or info.get("path") == name_or_path:
            target_slug = slug
            break

    if target_slug and target_slug in workspaces:
        del workspaces[target_slug]
        data["workspace"] = workspaces
        save_workspace_registry(data)
        return True
    return False


def list_workspaces() -> List[Dict[str, Any]]:
    """Return a list of all registered workspace dicts."""
    data = load_workspace_registry()
    workspaces = data.get("workspace", {})
    result = []
    for slug, info in workspaces.items():
        entry = dict(info)
        entry["slug"] = slug
        result.append(entry)
    return result
