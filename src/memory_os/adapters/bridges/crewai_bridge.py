from typing import Any, Optional, Type
from memory_os.core.repository import MemoryRepository

try:
    from crewai.tools import BaseTool
    from pydantic import BaseModel, Field
    HAS_CREWAI = True
except ImportError:
    HAS_CREWAI = False
    class BaseModel: pass
    class BaseTool: pass
    def Field(*args, **kwargs): return None

class MemorySearchInput(BaseModel):
    """Input schema for MemorySearchTool."""
    query: str = Field(..., description="The query to search in the Memory OS graph.")
    limit: int = Field(default=5, description="Maximum number of nodes to return.")

class MemorySearchTool(BaseTool):
    """
    CrewAI Tool to search the Memory OS Universal Graph.
    """
    name: str = "Memory OS Search"
    description: str = "Search the Memory OS graph for context, constraints, and architecture rules."
    args_schema: Type[BaseModel] = MemorySearchInput
    
    repo: Optional[MemoryRepository] = None

    def __init__(self, repo: MemoryRepository, **kwargs):
        if not HAS_CREWAI:
            raise ImportError("crewai is not installed. Please install it to use MemorySearchTool.")
        super().__init__(**kwargs)
        self.repo = repo

    def _run(self, query: str, limit: int = 5) -> str:
        if not self.repo:
            return "Error: MemoryRepository not provided."
        
        from memory_os.modules.search import MemorySearcher
        searcher = MemorySearcher(repository=self.repo)
        results = searcher.search_memory(query)
        
        if not results:
            return f"No results found in Memory OS for query: '{query}'."
            
        output = []
        for n in results[:limit]:
            output.append(f"- [{n.get('id')}] ({n.get('type')})\n  {n.get('summary')}")
            
        return "\n".join(output)
