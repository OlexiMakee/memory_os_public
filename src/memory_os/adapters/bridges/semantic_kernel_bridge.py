from typing import Any
from memory_os.core.repository import MemoryRepository

try:
    from semantic_kernel.functions.kernel_function_decorator import kernel_function
    HAS_SEMANTIC_KERNEL = True
except ImportError:
    HAS_SEMANTIC_KERNEL = False
    def kernel_function(*args, **kwargs):
        def decorator(func): return func
        return decorator

class MemoryOSPlugin:
    """
    Semantic Kernel Plugin that accesses the Memory OS Graph.
    """
    def __init__(self, repo: MemoryRepository):
        if not HAS_SEMANTIC_KERNEL:
            raise ImportError("semantic-kernel is not installed.")
        self.repo = repo

    @kernel_function(
        description="Search the Memory OS Universal Graph for architectural context, project rules, or domain constraints.",
        name="SearchMemoryOS"
    )
    def search_memory(self, query: str, limit: int = 5) -> str:
        from memory_os.modules.search import MemorySearcher
        
        searcher = MemorySearcher(repository=self.repo)
        results = searcher.search_memory(query)
        
        if not results:
            return "No memory found."
            
        lines = []
        for n in results[:limit]:
            lines.append(f"[{n.get('id')}] {n.get('summary')}")
            
        return "\n".join(lines)
