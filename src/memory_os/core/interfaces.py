from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Any, Optional

class IMemoryOSConfig(ABC):
    """Interface for Memory OS configurations."""

    @property
    @abstractmethod
    def profile(self) -> str:
        pass

    @property
    @abstractmethod
    def memory_dir(self) -> Path:
        pass

    @property
    @abstractmethod
    def capsules_file(self) -> Path:
        pass

    @property
    @abstractmethod
    def snapshot_file(self) -> Path:
        pass

    @property
    @abstractmethod
    def proposals_file(self) -> Path:
        pass

    @property
    @abstractmethod
    def workflows(self) -> List[str]:
        pass

    @property
    @abstractmethod
    def step_scale(self) -> str:
        pass

    @property
    @abstractmethod
    def resource_mode(self) -> str:
        """Returns 'quiet', 'normal', or 'max'."""
        pass

    @property
    @abstractmethod
    def db_path(self) -> Path:
        pass

    @property
    @abstractmethod
    def daemon_port(self) -> int:
        pass


class IMemoryStorage(ABC):
    """Interface for Memory OS JSONL and JSON storage, separating disk I/O."""

    @abstractmethod
    def load_jsonl(self, filepath: Path) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def save_jsonl(self, filepath: Path, items: List[Dict[str, Any]]) -> None:
        pass

    @abstractmethod
    def append_jsonl(self, filepath: Path, item: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    def load_json(self, filepath: Path) -> Dict[str, Any]:
        pass

    @abstractmethod
    def save_json(self, filepath: Path, item: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    def read_lines(self, filepath: Path) -> List[str]:
        pass

    @abstractmethod
    def exists(self, filepath: Path) -> bool:
        pass

    @abstractmethod
    def get_sha256(self, filepath: Path) -> str:
        pass


class ILlmProviderService(ABC):
    """Interface for LLM text completion/chat streaming."""

    @abstractmethod
    def call_llm(
        self,
        user_message: str,
        system_prompt: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> str:
        pass

class IHardwareScheduler(ABC):
    """Interface for managing hardware resources (e.g. CPU multiprocessing, memory caching) in Memory OS."""

    @abstractmethod
    def execute_parallel(self, func: Any, items: List[Any], max_workers: Optional[int] = None) -> List[Any]:
        """Execute a function in parallel across a list of items."""
        pass

    @abstractmethod
    def cache_get(self, key: str) -> Optional[Any]:
        """Retrieve an item from the fast memory cache."""
        pass

    @abstractmethod
    def cache_set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        """Store an item in the fast memory cache."""
        pass

    @abstractmethod
    def cache_invalidate(self, key: str) -> None:
        """Remove an item from the cache."""
        pass
