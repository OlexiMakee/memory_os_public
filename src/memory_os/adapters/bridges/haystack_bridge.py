from typing import Any, List, Dict
from memory_os.core.repository import MemoryRepository

try:
    from haystack import component
    from haystack import Document
    HAS_HAYSTACK = True
except ImportError:
    HAS_HAYSTACK = False
    def component(*args, **kwargs):
        if len(args) == 1 and callable(args[0]):
            return args[0]
        return lambda cls: cls
    component.output_types = lambda **kwargs: lambda f: f
    class Document: pass

@component
class MemoryOSRetriever:
    """
    Haystack component for retrieving documents from the Memory OS graph.
    """
    def __init__(self, repo: MemoryRepository, limit: int = 5):
        if not HAS_HAYSTACK:
            raise ImportError("haystack-ai is not installed.")
        self.repo = repo
        self.limit = limit

    @component.output_types(documents=List[Document])
    def run(self, query: str):
        from memory_os.modules.search import MemorySearcher
        
        searcher = MemorySearcher(repository=self.repo)
        results = searcher.search_memory(query)
        
        documents = []
        for n in results[:self.limit]:
            content = f"ID: {n.get('id')}\nSummary: {n.get('summary')}\nTags: {', '.join(n.get('tags', []))}\nEvidence: {', '.join(n.get('evidence', []))}"
            doc = Document(content=content, meta={"id": n.get('id'), "type": n.get('type')}, score=1.0)
            documents.append(doc)
            
        return {"documents": documents}
