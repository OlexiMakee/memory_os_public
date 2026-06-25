from typing import List, Optional, Any
from memory_os.core.repository import MemoryRepository

try:
    from llama_index.core.retrievers import BaseRetriever
    from llama_index.core.schema import NodeWithScore, TextNode
    from llama_index.core.callbacks.base import CallbackManager
    HAS_LLAMAINDEX = True
except ImportError:
    HAS_LLAMAINDEX = False
    class BaseRetriever: pass
    class NodeWithScore: pass
    class TextNode: pass

class MemoryOSRetriever(BaseRetriever):
    """
    LlamaIndex Retriever that fetches context from the Memory OS Graph.
    """
    def __init__(self, repo: MemoryRepository, limit: int = 5, callback_manager: Optional[Any] = None):
        if not HAS_LLAMAINDEX:
            raise ImportError("llama-index is not installed.")
        super().__init__(callback_manager=callback_manager)
        self.repo = repo
        self.limit = limit

    def _retrieve(self, query_bundle: Any) -> List[NodeWithScore]:
        from memory_os.modules.search import MemorySearcher
        
        query = query_bundle.query_str
        searcher = MemorySearcher(repository=self.repo)
        results = searcher.search_memory(query)
        
        llama_nodes = []
        for n in results[:self.limit]:
            text = f"ID: {n.get('id')}\nType: {n.get('type')}\nSummary: {n.get('summary')}\nTags: {', '.join(n.get('tags', []))}\nEvidence: {', '.join(n.get('evidence', []))}"
            node = TextNode(
                text=text,
                metadata={"id": n.get('id'), "type": n.get('type')}
            )
            llama_nodes.append(NodeWithScore(node=node, score=1.0))
            
        return llama_nodes
