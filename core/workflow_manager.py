from typing import Dict, List, Optional
from memory_os.core.module_interface import IMemoryModule, WorkflowProfile


class WorkflowManager:
    """Aggregates workflow profiles from all registered IMemoryModules."""
    
    def __init__(self):
        self._modules: List[IMemoryModule] = []
        
    def register_module(self, module: IMemoryModule) -> None:
        """Register a memory module to provide dynamic workflows."""
        self._modules.append(module)
        
    def get_registered_modules(self) -> List[IMemoryModule]:
        return self._modules
        
    def resolve_workflow(self, level: int) -> Optional[WorkflowProfile]:
        """
        Scan registered modules to find the first one that supports the given level
        and return its WorkflowProfile. If no module claims it, return None.
        """
        for module in self._modules:
            if level in module.get_supported_levels():
                profile = module.get_workflow_profile(level)
                if profile:
                    return profile
        return None
