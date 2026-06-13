from abc import ABC, abstractmethod
from typing import List, Dict, Any, Tuple, Optional
import time
import threading
from dataclasses import dataclass

@dataclass
class AuditorConfig:
    name: str
    interval_seconds: int
    requires_gpu: bool
    token_budget_cost: int

class IMemoryAuditor(ABC):
    """
    Base interface for all background memory analyzers.
    Supports stateful execution (idle, running, paused).
    """
    def __init__(self):
        self._state = "idle"  # idle, running, paused
        self._current_target: Optional[Tuple[str, str]] = None
        self._last_log: str = "Ready"

    @property
    @abstractmethod
    def config(self) -> AuditorConfig:
        pass

    @property
    def state(self) -> str:
        return self._state

    @state.setter
    def state(self, value: str):
        self._state = value

    @property
    def current_target(self) -> Optional[Tuple[str, str]]:
        return self._current_target

    @property
    def last_log(self) -> str:
        return self._last_log

    def log(self, msg: str):
        self._last_log = msg

    @abstractmethod
    def step(self) -> bool:
        """
        Executes one chunk of work. 
        Returns True if more work is pending, False if the pass is complete.
        """
        pass

    def reset(self):
        """Resets progress for a full run."""
        self._current_target = None
        self._last_log = "Reset"


class AuditorManager:
    """Manages the background execution of multiple auditors."""
    def __init__(self):
        self.auditors: Dict[str, IMemoryAuditor] = {}
        self.lock = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._thread.start()

    def register(self, auditor: IMemoryAuditor):
        with self.lock:
            self.auditors[auditor.config.name] = auditor

    def get_status(self) -> List[Dict[str, Any]]:
        with self.lock:
            status = []
            for name, aud in self.auditors.items():
                status.append({
                    "name": name,
                    "state": aud.state,
                    "current_target": aud.current_target,
                    "last_log": aud.last_log,
                    "requires_gpu": aud.config.requires_gpu
                })
            return status

    def start_auditor(self, name: str):
        with self.lock:
            if name in self.auditors:
                aud = self.auditors[name]
                if aud.state != "running":
                    aud.state = "running"
                    aud.log("Starting execution...")

    def pause_auditor(self, name: str):
        with self.lock:
            if name in self.auditors:
                aud = self.auditors[name]
                if aud.state == "running":
                    aud.state = "paused"
                    aud.log("Paused.")

    def stop_auditor(self, name: str):
        with self.lock:
            if name in self.auditors:
                aud = self.auditors[name]
                aud.state = "idle"
                aud.reset()
                aud.log("Stopped.")

    def shutdown(self):
        self._running = False

    def _worker_loop(self):
        while self._running:
            try:
                with self.lock:
                    active = [aud for aud in self.auditors.values() if aud.state == "running"]
                
                for aud in active:
                    if aud.state != "running":
                        continue
                    try:
                        has_more = aud.step()
                        if not has_more:
                            with self.lock:
                                aud.state = "idle"
                                aud.log("Pass complete. Idling.")
                    except Exception as e:
                        with self.lock:
                            aud.state = "idle"
                            aud.log(f"Error: {str(e)}")
                            
            except Exception:
                pass
            time.sleep(0.5)

# Example Mock Auditors for testing the UI
class MockMLEmbeddingAuditor(IMemoryAuditor):
    @property
    def config(self) -> AuditorConfig:
        return AuditorConfig("ML Embeddings (Stage 1)", 3600, True, 0)
        
    def step(self) -> bool:
        time.sleep(1) # simulate work
        self._current_target = ("class:App", f"mock_node_{int(time.time())}")
        self.log(f"Calculating cosine similarity for {self._current_target[1]}")
        return True # never finishes in mock

class MockOllamaAuditor(IMemoryAuditor):
    @property
    def config(self) -> AuditorConfig:
        return AuditorConfig("Ollama LLM (Stage 2)", 3600, False, 0)
        
    def step(self) -> bool:
        time.sleep(2) # simulate slower work
        self._current_target = ("file:main.py", f"test.fact.{int(time.time() % 10)}")
        self.log(f"Asking Ollama if {self._current_target[0]} contradicts {self._current_target[1]}")
        return True
