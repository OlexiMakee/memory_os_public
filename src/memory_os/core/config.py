import hashlib
import json
import os
from pathlib import Path
from typing import List, Dict, Any, Optional

from memory_os.core.interfaces import IMemoryOSConfig
from memory_os.core.safe_id import confine_to_root, validate_safe_id
from memory_os.toolkit.agent_registry import KNOWN_AGENTS

class MemoryOSConfig(IMemoryOSConfig):
    """Manages the configuration and paths for Memory OS."""

    def __init__(self, config_path: Optional[str] = None, space: str = "default"):
        self.space = validate_safe_id(space, "space")
        # 1. Resolve config file path: parameter -> env var -> default project root
        if config_path:
            self.config_path = Path(config_path).resolve()
        else:
            env_path = os.environ.get("MEMORY_OS_CONFIG_PATH")
            if env_path:
                self.config_path = Path(env_path).resolve()
            else:
                # Default to current working directory
                self.config_path = Path.cwd() / "memory_os.config.json"

        self.root_dir = self.config_path.parent
        self.data = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            # Fall back to default developer profile values if no config found
            return {
                "version": "0.1",
                "profile": "developer",
                "memory_dir": "memory",
                "capsules_file": "agent_context/task_capsules.jsonl",
                "snapshot_file": "agent_context/memory_snapshot.json",
                "workflows": ["product", "memory_os"],
                "step_scale": "1..12",
                "resource_mode": "normal",
                "db_path": "memory/memory_os.db",
                "budget": {
                    "max_daily_tokens": 50000
                }
            }
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    @property
    def profile(self) -> str:
        return self.data.get("profile", "developer")

    @property
    def memory_dir(self) -> Path:
        val = self.data.get("memory_dir", "memory")
        base = confine_to_root(val, self.root_dir)
        if self.space == "default":
            return base
        return (base / self.space).resolve()

    @property
    def internal_memory_dir(self) -> Path:
        return (Path(__file__).resolve().parent.parent / "memory_graph").resolve()

    @property
    def persona_memory_dir(self) -> Path:
        return (self.root_dir / "memory_os" / "user_persona").resolve()

    @property
    def capsules_file(self) -> Path:
        if self.space == "default":
            val = self.data.get("capsules_file", "agent_context/task_capsules.jsonl")
            return confine_to_root(val, self.root_dir)
        return self.memory_dir / "task_capsules.jsonl"

    @property
    def snapshot_file(self) -> Path:
        if self.space == "default":
            val = self.data.get("snapshot_file", "agent_context/memory_snapshot.json")
            return confine_to_root(val, self.root_dir)
        return self.memory_dir / "memory_snapshot.json"

    @property
    def proposals_file(self) -> Path:
        val = self.data.get("proposals_file", "agent_proposals/admin_proposals.jsonl")
        return confine_to_root(val, self.root_dir)

    @property
    def workflows(self) -> List[str]:
        return self.data.get("workflows", ["product", "memory_os"])

    @property
    def step_scale(self) -> str:
        return self.data.get("step_scale", "1..12")

    @property
    def resource_mode(self) -> str:
        return self.data.get("resource_mode", "normal")

    @property
    def db_path(self) -> Path:
        if self.space == "default":
            val = self.data.get("db_path", "memory/memory_os.db")
            return confine_to_root(val, self.root_dir)
        return self.memory_dir / "memory_os.db"

    @property
    def ui_port(self) -> int:
        return self.data.get("ui_port", 8080)

    @property
    def default_agent(self) -> str:
        return self.data.get("default_agent", "codex")

    @property
    def daemon_port(self) -> int:
        return self.data.get("daemon_port", 22467)

    @property
    def confidence_threshold(self) -> float:
        memory_cfg = self.data.get("memory", {})
        if isinstance(memory_cfg, dict) and "confidence_threshold" in memory_cfg:
            return float(memory_cfg["confidence_threshold"])
        return float(self.data.get("confidence_threshold", 0.7))

    @property
    def semantic_similarity_threshold(self) -> float:
        memory_cfg = self.data.get("memory", {})
        if isinstance(memory_cfg, dict):
            return float(memory_cfg.get("semantic_similarity_threshold", 0.60))
        return 0.60

    @property
    def semantic_fallback_threshold(self) -> float:
        memory_cfg = self.data.get("memory", {})
        if isinstance(memory_cfg, dict):
            return float(memory_cfg.get("semantic_fallback_threshold", 0.65))
        return 0.65

    @property
    def memory_roots(self) -> List[Path]:
        """Returns ordered list of memory roots for cascade resolution (Local > Configured > Global)."""
        roots: List[Path] = [self.root_dir]
        env_roots = os.environ.get("MEMORY_OS_ROOTS")
        if env_roots:
            for p in env_roots.split(":"):
                p_str = p.strip()
                if p_str:
                    p_path = Path(p_str).resolve()
                    if p_path.exists() and p_path not in roots:
                        roots.append(p_path)
        global_root = Path.home() / ".memory_os"
        if global_root.exists() and global_root not in roots:
            roots.append(global_root)
        return roots

    @property
    def workspace_id(self) -> str:
        return hashlib.sha256(str(self.root_dir).encode("utf-8")).hexdigest()[:12]

    @property
    def tmux_session_name(self) -> str:
        """Returns dynamic session name based on root directory name or hash."""
        slug = "".join(ch if ch.isalnum() else "_" for ch in self.root_dir.name.lower()).strip("_")
        if not slug or slug == "memory_os":
            return "memory_os_workspace"
        return f"memory_os_{slug}_{self.workspace_id[:8]}"

    @property
    def agent_panes(self) -> Dict[str, int]:
        """Returns mapping of agent IDs to pane indices."""
        res = {agent: i for i, agent in enumerate(KNOWN_AGENTS)}
        res["telegram-chat"] = len(KNOWN_AGENTS)
        return res
