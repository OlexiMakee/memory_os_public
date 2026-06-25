import json
import os
from importlib.util import find_spec
from typing import Dict, List

from memory_os.core.budget import BudgetManager
from memory_os.core.config import MemoryOSConfig
from memory_os.llm.routing import LLMRouter


def _adapter_installed(module_name: str) -> bool:
    try:
        return find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


PROVIDER_REGISTRY: Dict[str, Dict] = {
    "ollama": {
        "adapter_installed": _adapter_installed("ollama"),
        "env_key": None,
    },
    "litellm": {
        "adapter_installed": _adapter_installed("litellm"),
        "env_key": "LITELLM_API_KEY",
    },
    "gemini": {
        "adapter_installed": (
            _adapter_installed("google.genai")
            or _adapter_installed("google.generativeai")
        ),
        "env_key": "GEMINI_API_KEY",
    },
    "openrouter": {
        "adapter_installed": _adapter_installed("openai"),
        "env_key": "OPENROUTER_API_KEY",
    },
    "openai": {
        "adapter_installed": _adapter_installed("openai"),
        "env_key": "OPENAI_API_KEY",
    },
}


class RoutingPolicy:
    """CLI-facing model routing and budget policy for Stage 9."""

    MAX_TASK_BUDGET_ENTRIES = 500

    _TASK_KEYWORDS = (
        (
            "memory_compaction",
            (
                "compact",
                "compaction",
                "summarize memory",
                "compress memory",
                "memory cleanup",
            ),
        ),
        (
            "jsonl_extraction",
            (
                "jsonl",
                "extract",
                "parse",
                "evidence",
                "structured data",
            ),
        ),
        (
            "tagging",
            (
                "tag",
                "tags",
                "label",
                "labels",
                "categorize",
                "category",
            ),
        ),
        (
            "classification",
            (
                "classify",
                "classification",
                "triage",
                "rank",
                "prioritize",
            ),
        ),
        (
            "short_rewrite",
            (
                "rewrite",
                "format",
                "formatting",
                "copy edit",
                "shorten",
                "polish",
            ),
        ),
        (
            "fast_mac_inference",
            (
                "fast mac",
                "apple silicon",
                "mlx",
                "local inference",
            ),
        ),
        (
            "local_chat",
            (
                "local chat",
                "offline chat",
                "chat locally",
            ),
        ),
        (
            "batch_generation",
            (
                "batch",
                "bulk generate",
                "generate many",
            ),
        ),
        (
            "multi_user_serving",
            (
                "multi user",
                "multi-user",
                "serve users",
                "serving",
            ),
        ),
        (
            "heavy_parallel",
            (
                "parallel",
                "concurrent",
                "many requests",
                "high throughput",
            ),
        ),
        (
            "deep_architecture",
            (
                "architecture",
                "design",
                "system design",
                "roadmap",
                "strategy",
            ),
        ),
        (
            "high_stakes_analysis",
            (
                "security",
                "audit",
                "compliance",
                "risk",
                "privacy",
                "credentials",
                "secrets",
            ),
        ),
        (
            "agentic_reasoning",
            (
                "review",
                "bugs",
                "debug",
                "reason",
                "agent",
                "implement",
                "fix",
                "investigate",
                "analyze",
            ),
        ),
    )

    def __init__(self, config: MemoryOSConfig):
        self.config = config
        self.router = LLMRouter()
        self.budget = BudgetManager(config)
        self.data_dir = config.root_dir / "data"
        self.task_budget_file = self.data_dir / "budget_by_task.json"

    def route(self, task: str, format: str = "json") -> Dict:
        del format
        task_type = self._task_type_for(task)
        decision = self.router.route(task_type)
        return {
            "task": task,
            "task_type": task_type,
            "provider": decision.provider,
            "model": decision.model,
            "reason": decision.reason,
        }

    def budget_status(self) -> Dict:
        tokens_used = int(self.budget._state.get("tokens_used", 0))
        daily_budget = int(self.budget.daily_budget)
        return {
            "tokens_used": tokens_used,
            "daily_budget": daily_budget,
            "remaining": int(self.budget.get_remaining()),
            "exhausted": bool(self.budget.is_budget_exhausted()),
        }

    def record_task_usage(self, task_id: str, tokens: int) -> None:
        token_count = int(tokens)
        if token_count < 0:
            raise ValueError("tokens must be non-negative")

        self.budget.add_usage(token_count)

        task_budget = self._load_task_budget()
        normalized_task_id = str(task_id)
        if normalized_task_id in task_budget:
            task_budget[normalized_task_id] = (
                int(task_budget.get(normalized_task_id, 0)) + token_count
            )
        else:
            task_budget[normalized_task_id] = token_count

        while len(task_budget) > self.MAX_TASK_BUDGET_ENTRIES:
            oldest_key = next(iter(task_budget))
            del task_budget[oldest_key]

        self._save_task_budget(task_budget)

    def list_providers(self) -> List[Dict]:
        providers = []
        for name, metadata in PROVIDER_REGISTRY.items():
            env_key = metadata.get("env_key")
            providers.append(
                {
                    "name": name,
                    "adapter_installed": bool(metadata.get("adapter_installed")),
                    "configured": True if env_key is None else bool(os.environ.get(env_key)),
                }
            )
        return providers

    def test_provider(self, name: str) -> Dict:
        metadata = PROVIDER_REGISTRY.get(name)
        if metadata is None:
            return {"name": name, "ok": False, "detail": "unknown provider"}

        if not metadata.get("adapter_installed"):
            return {"name": name, "ok": False, "detail": "adapter not installed"}

        env_key = metadata.get("env_key")
        if env_key and not os.environ.get(env_key):
            return {"name": name, "ok": False, "detail": f"{env_key} not configured"}

        return {"name": name, "ok": True, "detail": "offline check passed"}

    def _task_type_for(self, task: str) -> str:
        normalized = task.lower()
        for task_type, keywords in self._TASK_KEYWORDS:
            if any(keyword in normalized for keyword in keywords):
                return task_type
        return "agentic_reasoning"

    def _load_task_budget(self) -> Dict[str, int]:
        if not self.task_budget_file.exists():
            return {}
        try:
            with open(self.task_budget_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}

        task_budget: Dict[str, int] = {}
        for task_id, tokens in data.items():
            try:
                task_budget[str(task_id)] = int(tokens)
            except (TypeError, ValueError):
                continue
        return task_budget

    def _save_task_budget(self, task_budget: Dict[str, int]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with open(self.task_budget_file, "w", encoding="utf-8") as f:
            json.dump(task_budget, f)
