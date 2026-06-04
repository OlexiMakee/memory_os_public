from typing import Dict, Any, List, Optional
from abc import ABC, abstractmethod


class WorkflowProfile:
    """Represents an active workflow profile derived from a module or standard config."""
    def __init__(self, level: int, memory_policy: Dict[str, Any], compute_policy: Dict[str, Any], tools: List[str]):
        self.level = level
        self.memory_policy = memory_policy
        self.compute_policy = compute_policy
        self.tools = tools


class IMemoryModule(ABC):
    """
    Standard interface for all Memory OS pluggable modules (e.g., LocalGPU, WebScraper, CodeIndexer).
    Modules provide dynamic workflows mapping to the 0-13 scale.
    """
    
    @abstractmethod
    def get_manifest(self) -> Dict[str, Any]:
        """
        Return the module manifest containing name, version, and dependencies.
        Example: {"name": "gpu_ml_cluster", "version": "1.0", "hardware": {"vram_gb": 8}}
        """
        pass

    @abstractmethod
    def get_supported_levels(self) -> List[int]:
        """
        Return the 0-13 levels supported by this module.
        Example: [0, 8, 9]
        """
        pass

    @abstractmethod
    def get_workflow_profile(self, level: int) -> Optional[WorkflowProfile]:
        """
        Return the workflow profile config for a specific level.
        If the level is not supported, return None.
        """
        pass
