from typing import List, Dict, Any, Optional
from memory_os.core.interfaces import IMemoryStorage, IMemoryOSConfig
from memory_os.core.models import MemoryNode, MemoryEdge, TaskCapsule

class MemoryRepository:
    """Repository pattern abstracting direct file/database operations for Memory OS."""

    def __init__(self, storage: IMemoryStorage, config: IMemoryOSConfig, indexer: Optional[Any] = None):
        self.storage = storage
        self.config = config
        self.indexer = indexer

    def _get_nodes_path(self):
        return self.config.memory_dir / "nodes.jsonl"

    def _get_edges_path(self):
        return self.config.memory_dir / "edges.jsonl"

    def _get_capsules_path(self):
        return self.config.capsules_file

    def _get_patches_path(self):
        return self.config.memory_dir / "patches.jsonl"

    def get_nodes(self) -> List[MemoryNode]:
        raw = self.storage.load_jsonl(self._get_nodes_path())
        internal_raw = self.storage.load_jsonl(self.config.internal_memory_dir / "nodes.jsonl")
        return [MemoryNode.from_dict(d) for d in raw + internal_raw]

    def add_node(self, node: MemoryNode) -> None:
        self.storage.append_jsonl(self._get_nodes_path(), node.to_dict())
        if self.indexer:
            self.indexer.index_node(node)

    def save_nodes(self, nodes: List[MemoryNode]) -> None:
        raw = [n.to_dict() for n in nodes]
        self.storage.save_jsonl(self._get_nodes_path(), raw)
        self.sync_graph_nodes()

    def sync_graph_nodes(self) -> None:
        from memory_os.core.core import MemoryOS
        db = MemoryOS(self.config)
        nodes = self.get_nodes()
        for n in nodes:
            db.insert_graph_node(
                node_id=n.id,
                node_type=n.type,
                summary=n.summary,
                status=n.status,
                freshness=n.freshness,
                trust=n.trust,
                tags=",".join(n.tags) if n.tags else None
            )

    def get_edges(self) -> List[MemoryEdge]:
        raw = self.storage.load_jsonl(self._get_edges_path())
        return [MemoryEdge.from_dict(d) for d in raw]

    def add_edge(self, edge: MemoryEdge) -> None:
        self.storage.append_jsonl(self._get_edges_path(), edge.to_dict())
        if self.indexer:
            self.indexer.index_edge(edge)

    def save_edges(self, edges: List[MemoryEdge]) -> None:
        raw = [e.to_dict() for e in edges]
        self.storage.save_jsonl(self._get_edges_path(), raw)

    def get_task_capsules(self) -> List[TaskCapsule]:
        raw = self.storage.load_jsonl(self._get_capsules_path())
        return [TaskCapsule.from_dict(d) for d in raw]

    def add_task_capsule(self, capsule: TaskCapsule) -> None:
        self.storage.append_jsonl(self._get_capsules_path(), capsule.to_dict())

    def get_patches(self) -> List[Any]:
        from memory_os.core.patch import RelationPatch
        raw = self.storage.load_jsonl(self._get_patches_path())
        return [RelationPatch(**d) for d in raw]

    def save_patch(self, patch: Any) -> None:
        from dataclasses import asdict
        self.storage.append_jsonl(self._get_patches_path(), asdict(patch))
