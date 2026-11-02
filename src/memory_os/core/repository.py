from dataclasses import asdict
from typing import List, Dict, Any, Optional
from memory_os.core.interfaces import IMemoryStorage, IMemoryOSConfig
from memory_os.core.models import MemoryNode, MemoryEdge, TaskCapsule
from memory_os.core.registry import RelationContractRegistry
from memory_os.core.timecode import now_local_iso

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

    def _get_events_path(self):
        return self.config.memory_dir / "events.jsonl"

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
        local_nodes = self.get_local_nodes()
        internal_raw = self.storage.load_jsonl(self.config.internal_memory_dir / "nodes.jsonl")
        return local_nodes + [MemoryNode.from_dict(d) for d in internal_raw]

    def get_local_nodes(self) -> List[MemoryNode]:
        raw = self.storage.load_jsonl(self._get_nodes_path())
        return [MemoryNode.from_dict(d) for d in raw]

    def _append_event(self, event: Dict[str, Any]) -> None:
        self.storage.append_jsonl(self._get_events_path(), event)

    def _save_events(self, events: List[Dict[str, Any]]) -> None:
        self.storage.save_jsonl(self._get_events_path(), events)

    def _indexer(self) -> Any:
        if self.indexer is not None:
            return self.indexer
        from memory_os.core.core import MemoryOS
        self.indexer = MemoryOS(self.config)
        return self.indexer

    def sync_graph_nodes(self) -> None:
        db = self._indexer()
        nodes = self.get_nodes()
        conn = db.get_connection()
        try:
            conn.execute("DELETE FROM graph_nodes")
            for n in nodes:
                tags = ",".join(n.tags) if n.tags else None
                conn.execute("""
                    INSERT INTO graph_nodes (id, type, summary, status, freshness, trust, tags)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (n.id, n.type, n.summary, n.status, n.freshness, n.trust, tags))
            conn.commit()
        finally:
            conn.close()

    def sync_graph_edges(self) -> None:
        db = self._indexer()
        edges = self.get_edges()
        conn = db.get_connection()
        try:
            conn.execute("DELETE FROM graph_edges")
            for e in edges:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO graph_edges (source, target, type)
                    VALUES (?, ?, ?)
                    """,
                    (e.source, e.target, e.type),
                )
            conn.commit()
        finally:
            conn.close()

    def sync_sqlite(self) -> None:
        """Mirror canonical JSONL graph state into the SQLite search index."""
        self.sync_graph_nodes()
        self.sync_graph_edges()

    def get_edges(self) -> List[MemoryEdge]:
        raw = self.storage.load_jsonl(self._get_edges_path())
        return [MemoryEdge.from_dict(d) for d in raw]

    def get_events(self) -> List[Dict[str, Any]]:
        return self.storage.load_jsonl(self._get_events_path())

    def emit_event(self, event: Dict[str, Any], sync: bool = False) -> None:
        """Append a graph lifecycle event through the central mutation API."""
        self._append_event(event)
        if sync:
            self.sync_sqlite()

    def replace_events(self, events: List[Dict[str, Any]], sync: bool = False) -> None:
        self._save_events(events)
        if sync:
            self.sync_sqlite()

    def replace_nodes(self, nodes: List[Dict[str, Any] | MemoryNode], events: Optional[List[Dict[str, Any]]] = None) -> None:
        from memory_os.core.patch import RelationPatchStore
        patch = self._make_patch(
            operation="replace_nodes",
            target="memory/nodes.jsonl",
            payload={"nodes": [n.to_dict() if isinstance(n, MemoryNode) else dict(n) for n in nodes]},
            reason="replace canonical node set",
        )
        store = RelationPatchStore(self)
        patch_id = store.propose(patch)
        store.apply(patch_id, events=events)

    def replace_edges(self, edges: List[Dict[str, Any] | MemoryEdge], events: Optional[List[Dict[str, Any]]] = None) -> None:
        from memory_os.core.patch import RelationPatchStore
        patch = self._make_patch(
            operation="replace_edges",
            target="memory/edges.jsonl",
            payload={"edges": [e.to_dict() if isinstance(e, MemoryEdge) else dict(e) for e in edges]},
            reason="replace canonical edge set",
        )
        store = RelationPatchStore(self)
        patch_id = store.propose(patch)
        store.apply(patch_id, events=events)

    def upsert_node(self, node: Dict[str, Any] | MemoryNode, events: Optional[List[Dict[str, Any]]] = None) -> None:
        from memory_os.core.patch import RelationPatchStore
        raw = node.to_dict() if isinstance(node, MemoryNode) else dict(node)
        patch = self._make_patch(
            operation="upsert_node",
            target=raw.get("id", ""),
            patch_type=raw.get("type", "fact"),
            confidence=float(raw.get("confidence", 1.0) or 1.0),
            evidence=raw.get("evidence", []),
            payload={"node": raw},
            reason=f"upsert node {raw.get('id', '')}",
        )
        store = RelationPatchStore(self)
        patch_id = store.propose(patch)
        store.apply(patch_id, events=events)

    def upsert_edge(self, edge: Dict[str, Any] | MemoryEdge, events: Optional[List[Dict[str, Any]]] = None) -> None:
        self.upsert_edge_with_protocol(edge, events=events)

    def upsert_edge_with_protocol(
        self,
        edge: Dict[str, Any] | MemoryEdge,
        protocol_level: Optional[int] = None,
        events: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        from memory_os.core.patch import RelationPatchStore
        raw = edge.to_dict() if isinstance(edge, MemoryEdge) else dict(edge)
        created_by_protocol, required_verification_protocol = self._edge_protocols(
            str(raw.get("type", "")),
            protocol_level,
        )
        patch = self._make_patch(
            operation="upsert_edge",
            source=raw.get("source", ""),
            target=raw.get("target", ""),
            patch_type=raw.get("type", ""),
            domain=raw.get("domain", ""),
            confidence=float(raw.get("confidence", 1.0) or 1.0),
            evidence=raw.get("evidence", []),
            payload={"edge": raw},
            reason=raw.get("reason", f"upsert edge {raw.get('source', '')}->{raw.get('target', '')}"),
            created_by_protocol=created_by_protocol,
            required_verification_protocol=required_verification_protocol,
        )
        store = RelationPatchStore(self)
        patch_id = store.propose(patch)
        store.apply(patch_id, events=events)

    def _edge_protocols(self, edge_type: str, protocol_level: Optional[int]) -> tuple[int, int]:
        if protocol_level is not None:
            return protocol_level, protocol_level

        contract = RelationContractRegistry().get_contract(edge_type)
        if contract and contract.deterministic:
            level = max(
                contract.default_protocol_level,
                contract.min_create_protocol,
                contract.min_verify_protocol,
            )
            return level, level
        return 0, 0

    def update_node(self, node_id: str, updates: Dict[str, Any], events: Optional[List[Dict[str, Any]]] = None) -> bool:
        from memory_os.core.patch import RelationPatchStore
        patch = self._make_patch(
            operation="update_node",
            target=node_id,
            payload={"updates": dict(updates)},
            reason=f"update node {node_id}",
        )
        store = RelationPatchStore(self)
        patch_id = store.propose(patch)
        return store.apply(patch_id, events=events)

    def archive_nodes(self, nodes: List[Dict[str, Any] | MemoryNode]) -> None:
        archive_path = self.config.memory_dir / "archived_nodes.jsonl"
        for node in nodes:
            raw = node.to_dict() if isinstance(node, MemoryNode) else dict(node)
            self.storage.append_jsonl(archive_path, raw)

    def archive_edges(self, edges: List[Dict[str, Any] | MemoryEdge]) -> None:
        archive_path = self.config.memory_dir / "archived_edges.jsonl"
        for edge in edges:
            raw = edge.to_dict() if isinstance(edge, MemoryEdge) else dict(edge)
            self.storage.append_jsonl(archive_path, raw)

    def _make_patch(
        self,
        operation: str,
        target: str,
        patch_type: str = "fact",
        source: str = "",
        domain: str = "",
        confidence: float = 1.0,
        evidence: Optional[List[str]] = None,
        payload: Optional[Dict[str, Any]] = None,
        reason: str = "",
        created_by_protocol: int = 0,
        required_verification_protocol: int = 0,
    ) -> Any:
        from memory_os.core.patch import RelationPatch
        return RelationPatch(
            operation=operation,
            source=source,
            target=target,
            type=patch_type,
            domain=domain,
            confidence=confidence,
            evidence=evidence or [],
            reason=reason,
            created_by_protocol=created_by_protocol,
            required_verification_protocol=required_verification_protocol,
            payload=payload or {},
        )

    def apply_patch(self, patch: Any, events: Optional[List[Dict[str, Any]]] = None, sync: bool = True) -> bool:
        """Apply a validated graph patch.

        This is the only public API that mutates the canonical memory graph
        files. JSONL remains the source of truth; SQLite is refreshed after
        node/edge mutations as a derived index.
        """
        changed_graph = False

        if patch.operation == "upsert_node":
            raw = dict(patch.payload.get("node") or {})
            if not raw:
                raw = {
                    "id": patch.target,
                    "type": patch.type,
                    "summary": patch.payload.get("summary", ""),
                    "evidence": patch.evidence,
                    "status": patch.payload.get("status", "draft"),
                    "freshness": patch.payload.get("freshness", now_local_iso(self.config)),
                    "trust": patch.payload.get("trust", "verified" if patch.confidence > 0.8 else "unverified"),
                    "domain": patch.domain,
                    "related_nodes": patch.payload.get("related_nodes", []),
                    "tags": patch.payload.get("tags", []),
                    "confidence": patch.confidence,
                }
            raw.setdefault("confidence", patch.confidence)
            nodes = self.storage.load_jsonl(self._get_nodes_path())
            replaced = False
            for idx, node in enumerate(nodes):
                if node.get("id") == raw.get("id"):
                    merged = dict(node)
                    merged.update(raw)
                    nodes[idx] = merged
                    replaced = True
                    break
            if replaced:
                self.storage.save_jsonl(self._get_nodes_path(), nodes)
            else:
                self.storage.append_jsonl(self._get_nodes_path(), raw)
            changed_graph = True

        elif patch.operation == "update_node":
            nodes = self.storage.load_jsonl(self._get_nodes_path())
            updates = dict(patch.payload.get("updates") or {})
            found = False
            for node in nodes:
                if node.get("id") == patch.target:
                    node.update(updates)
                    found = True
                    break
            if not found:
                return False
            self.storage.save_jsonl(self._get_nodes_path(), nodes)
            changed_graph = True

        elif patch.operation == "replace_nodes":
            nodes = [dict(n) for n in patch.payload.get("nodes", [])]
            self.storage.save_jsonl(self._get_nodes_path(), nodes)
            changed_graph = True

        elif patch.operation == "upsert_edge":
            raw = dict(patch.payload.get("edge") or {})
            if not raw:
                raw = {
                    "source": patch.source,
                    "target": patch.target,
                    "type": patch.type,
                    "domain": patch.domain,
                    "confidence": patch.confidence,
                    "evidence": patch.evidence,
                    "reason": patch.reason,
                }
            edges = self.storage.load_jsonl(self._get_edges_path())
            key = (raw.get("source"), raw.get("target"), raw.get("type"))
            replaced = False
            for idx, edge in enumerate(edges):
                if (edge.get("source"), edge.get("target"), edge.get("type")) == key:
                    merged = dict(edge)
                    merged.update(raw)
                    edges[idx] = merged
                    replaced = True
                    break
            if replaced:
                self.storage.save_jsonl(self._get_edges_path(), edges)
            else:
                self.storage.append_jsonl(self._get_edges_path(), raw)
            changed_graph = True

        elif patch.operation == "delete_edge_soft":
            edges = self.storage.load_jsonl(self._get_edges_path())
            new_edges = [
                e for e in edges
                if not (e.get("source") == patch.source and e.get("target") == patch.target and e.get("type") == patch.type)
            ]
            if len(new_edges) == len(edges):
                return False
            self.storage.save_jsonl(self._get_edges_path(), new_edges)
            changed_graph = True

        elif patch.operation == "replace_edges":
            edges = [dict(e) for e in patch.payload.get("edges", [])]
            self.storage.save_jsonl(self._get_edges_path(), edges)
            changed_graph = True

        elif patch.operation == "replace_events":
            events_payload = [dict(e) for e in patch.payload.get("events", [])]
            self.storage.save_jsonl(self._get_events_path(), events_payload)

        elif patch.operation == "deprecate_node":
            nodes = self.storage.load_jsonl(self._get_nodes_path())
            found = False
            now = now_local_iso(self.config)
            for node in nodes:
                if node.get("id") == patch.target:
                    node["status"] = patch.payload.get("status", "stale")
                    node["valid_until"] = patch.payload.get("valid_until", now)
                    node["freshness"] = patch.payload.get("freshness", now)
                    found = True
                    break
            if not found:
                return False
            self.storage.save_jsonl(self._get_nodes_path(), nodes)
            changed_graph = True

        else:
            raise ValueError(f"Unsupported RelationPatch operation: {patch.operation}")

        for event in events or []:
            self._append_event(event)

        if changed_graph and sync:
            from memory_os.modules.search import MemorySearcher
            searcher = MemorySearcher(config=self.config, repository=self)
            searcher.incremental_sync(patch)
        return True

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
        self.storage.append_jsonl(self._get_patches_path(), asdict(patch))
