from typing import List, Any, Optional, Dict
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
import time
import multiprocessing
from memory_os.core.interfaces import IHardwareScheduler

class HardwareScheduler(IHardwareScheduler):
    """Implementation of IHardwareScheduler using multiprocessing and an in-memory cache."""

    def __init__(self, mode: str = "normal"):
        self.mode = mode
        self._cache: Dict[str, Dict[str, Any]] = {}
        
        # Determine concurrency based on mode
        cpu_count = multiprocessing.cpu_count()
        if mode == "max":
            self.max_workers = cpu_count
        elif mode == "quiet":
            self.max_workers = max(1, cpu_count // 4)
        else:
            self.max_workers = max(1, cpu_count // 2)

    def execute_parallel(self, func: Any, items: List[Any], max_workers: Optional[int] = None) -> List[Any]:
        """Execute a function in parallel across items. Uses ThreadPool for I/O bounds by default.
        Could be expanded to switch to ProcessPool for CPU-bound tasks.

        Isolates per-item failures instead of letting the first worker
        exception propagate and discard every other already-completed
        result (executor.map's old behavior) — a malformed single item
        (e.g. one bad LLM batch) no longer aborts the whole call. Order is
        preserved to match the previous executor.map-based contract.
        """
        workers = max_workers if max_workers else self.max_workers
        results: List[Any] = [None] * len(items)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_index = {executor.submit(func, item): i for i, item in enumerate(items)}
            for future in as_completed(future_to_index):
                i = future_to_index[future]
                try:
                    results[i] = future.result()
                except Exception as exc:
                    results[i] = {"ok": False, "item": items[i], "error": str(exc)}
        return results

    def cache_get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            entry = self._cache[key]
            if entry["expires_at"] is None or entry["expires_at"] > time.time():
                return entry["value"]
            else:
                del self._cache[key]
        return None

    def cache_set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        expires_at = time.time() + ttl_seconds if ttl_seconds else None
        self._cache[key] = {
            "value": value,
            "expires_at": expires_at
        }

    def cache_invalidate(self, key: str) -> None:
        if key in self._cache:
            del self._cache[key]

    def clear_expired_cache(self) -> None:
        """Utility to periodically clean up the cache."""
        now = time.time()
        expired_keys = [k for k, v in self._cache.items() if v["expires_at"] and v["expires_at"] < now]
        for k in expired_keys:
            del self._cache[k]
