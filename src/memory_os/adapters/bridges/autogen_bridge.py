from typing import Callable, List, Dict, Any
from memory_os.core.repository import MemoryRepository

def get_autogen_tools(repo: MemoryRepository) -> List[Callable]:
    """
    Returns a list of functions that can be registered with AutoGen agents using:
    autogen.agentchat.register_function(tool, caller=..., executor=...)
    """
    def search_memory(query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search the Memory OS Universal Graph for relevant context nodes."""
        from memory_os.modules.search import MemorySearcher
        searcher = MemorySearcher(repository=repo)
        results = searcher.search_memory(query)
        return [{"id": n.get("id"), "type": n.get("type"), "summary": n.get("summary")} for n in results[:limit]]

    def get_node_details(node_id: str) -> Dict[str, Any]:
        """Retrieve full details of a specific Memory OS node by ID."""
        node = next((n for n in repo.get_nodes() if n.id == node_id), None)
        if not node:
            return {"error": f"Node {node_id} not found."}
        
        edges = [e for e in repo.get_edges() if e.source == node_id or e.target == node_id]
        return {
            "id": node.id,
            "type": node.type,
            "summary": node.summary,
            "tags": node.tags,
            "evidence": node.evidence,
            "connected_edges": len(edges)
        }

    return [search_memory, get_node_details]
