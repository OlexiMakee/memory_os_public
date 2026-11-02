import json
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

class QuotaStore:
    """Centralized persistence for quota monitor state."""
    
    def __init__(self, root: Path):
        self.root = root
        self.state_file = self.root / "agent_context" / "agents" / "quota_monitor_state.json"

    def load(self) -> Dict[str, Any]:
        """Load the quota monitor state from disk."""
        if not self.state_file.exists():
            return {}
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def save(self, state: Dict[str, Any]) -> None:
        """Save the quota monitor state to disk."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception as e:
            logger.error(f"[quota_store] failed to save state: {e}")
