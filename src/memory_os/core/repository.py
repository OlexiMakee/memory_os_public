import warnings
from typing import List, Dict, Any, Optional
from memory_os.core.interfaces import IMemoryStorage, IMemoryOSConfig
from memory_os.core.models import MemoryNode, MemoryEdge, TaskCapsule

_DIRECT_MUTATION_WARNING = (
    "{method} is deprecated. Use RelationPatchStore.propose()+apply() "
    "to mutate the graph so all changes are validated and auditable."
)


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

    def get_version_hash(self) -> str:
        """Returns a fast string representing the current state version to invalidate caches."""
        import os
        nodes_path = self._get_nodes_path()
        mtime = os.path.getmtime(nodes_path) if nodes_path.exists() else 0.0
        return f"v_{mtime}"

    def _get_capsules_path(self):
        return self.config.capsules_file

    def _get_patches_path(self):
        return self.config.memory_dir / "patches.jsonl"

    def get_nodes(self) -> List[MemoryNode]:
        raw = self.storage.load_jsonl(self._get_nodes_path())
        internal_raw = self.storage.load_jsonl(self.config.internal_memory_dir / "nodes.jsonl")
        return [MemoryNode.from_dict(d) for d in raw + internal_raw]

    # ------------------------------------------------------------------
    # Private mutation methods — called only by RelationPatchStore.apply()
    # ------------------------------------------------------------------

    def _add_node(self, node: MemoryNode) -> None:
        self.storage.append_jsonl(self._get_nodes_path(), node.to_dict())
        if self.indexer:
            self.indexer.index_node(node)

    def _save_nodes(self, nodes: List[MemoryNode]) -> None:
        raw = [n.to_dict() for n in nodes]
        self.storage.save_jsonl(self._get_nodes_path(), raw)
        self.sync_graph_nodes()

    def _add_edge(self, edge: MemoryEdge) -> None:
        self.storage.append_jsonl(self._get_edges_path(), edge.to_dict())
        if self.indexer:
            self.indexer.index_edge(edge)

    def _save_edges(self, edges: List[MemoryEdge]) -> None:
        raw = [e.to_dict() for e in edges]
        self.storage.save_jsonl(self._get_edges_path(), raw)

    # ------------------------------------------------------------------
    # Deprecated public API — kept for backwards compatibility only
    # ------------------------------------------------------------------

    def add_node(self, node: MemoryNode) -> None:
        warnings.warn(
            _DIRECT_MUTATION_WARNING.format(method="MemoryRepository.add_node"),
            DeprecationWarning,
            stacklevel=2,
        )
        self._add_node(node)

    def save_nodes(self, nodes: List[MemoryNode]) -> None:
        warnings.warn(
            _DIRECT_MUTATION_WARNING.format(method="MemoryRepository.save_nodes"),
            DeprecationWarning,
            stacklevel=2,
        )
        self._save_nodes(nodes)

    def add_edge(self, edge: MemoryEdge) -> None:
        warnings.warn(
            _DIRECT_MUTATION_WARNING.format(method="MemoryRepository.add_edge"),
            DeprecationWarning,
            stacklevel=2,
        )
        self._add_edge(edge)

    def save_edges(self, edges: List[MemoryEdge]) -> None:
        warnings.warn(
            _DIRECT_MUTATION_WARNING.format(method="MemoryRepository.save_edges"),
            DeprecationWarning,
            stacklevel=2,
        )
        self._save_edges(edges)

    # ------------------------------------------------------------------

    def sync_graph_nodes(self) -> None:
        from memory_os.core.core import MemoryOS
        db = MemoryOS(self.config)
        nodes = self.get_nodes()
        conn = db.get_connection()
        try:
            for n in nodes:
                tags = ",".join(n.tags) if n.tags else None
                conn.execute("""
                    INSERT INTO graph_nodes (id, type, summary, status, freshness, trust, tags)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        type = excluded.type,
                        summary = excluded.summary,
                        status = excluded.status,
                        freshness = excluded.freshness,
                        trust = excluded.trust,
                        tags = excluded.tags
                """, (n.id, n.type, n.summary, n.status, n.freshness, n.trust, tags))
            conn.commit()
        finally:
            conn.close()

    def get_edges(self) -> List[MemoryEdge]:
        raw = self.storage.load_jsonl(self._get_edges_path())
        return [MemoryEdge.from_dict(d) for d in raw]

    def get_task_capsules(self) -> List[TaskCapsule]:
        raw = self.storage.load_jsonl(self._get_capsules_path())
        return [TaskCapsule.from_dict(d) for d in raw]

    def add_task_capsule(self, capsule: TaskCapsule) -> None:
        self.storage.append_jsonl(self._get_capsules_path(), capsule.to_dict())

    def get_patches(self) -> List[Any]:
        from memory_os.core.patch import RelationPatch
        raw = self.storage.load_jsonl(self._get_patches_path())
        deduped = {}
        for d in raw:
            patch = RelationPatch.from_dict(d)
            deduped[patch.id] = patch
        return list(deduped.values())

    def save_patch(self, patch: Any) -> None:
        from dataclasses import asdict
        self.storage.append_jsonl(self._get_patches_path(), asdict(patch))
