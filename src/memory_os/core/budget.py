import json
import datetime
from pathlib import Path
from typing import Dict, Any
from memory_os.core.config import MemoryOSConfig

class BudgetManager:
    def __init__(self, config: MemoryOSConfig):
        self.config = config
        # Default budget if not specified
        self.daily_budget = self.config.data.get("budget", {}).get("max_daily_tokens", 50000)
        self.data_dir = config.root_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.data_dir / "budget_state.json"
        self._state = self._load_state()

    def _get_today_str(self) -> str:
        return datetime.date.today().isoformat()

    def _load_state(self) -> Dict[str, Any]:
        if not self.state_file.exists():
            return {"date": self._get_today_str(), "tokens_used": 0}
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
                
            # Reset if it's a new day
            if state.get("date") != self._get_today_str():
                return {"date": self._get_today_str(), "tokens_used": 0}
            return state
        except Exception:
            return {"date": self._get_today_str(), "tokens_used": 0}

    def _save_state(self):
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self._state, f)
        except Exception as e:
            pass

    def add_usage(self, tokens: int):
        """Record usage of tokens."""
        # Ensure date is current
        today = self._get_today_str()
        if self._state.get("date") != today:
            self._state = {"date": today, "tokens_used": 0}
            
        self._state["tokens_used"] = self._state.get("tokens_used", 0) + tokens
        self._save_state()

    def is_budget_exhausted(self) -> bool:
        """Check if the daily budget is exhausted."""
        today = self._get_today_str()
        if self._state.get("date") != today:
            self._state = {"date": today, "tokens_used": 0}
            self._save_state()
            
        return self._state.get("tokens_used", 0) >= self.daily_budget

    def get_remaining(self) -> int:
        today = self._get_today_str()
        if self._state.get("date") != today:
            return self.daily_budget
        return max(0, self.daily_budget - self._state.get("tokens_used", 0))
