from typing import Any, Dict, List, Optional

from memory_os.core.config import MemoryOSConfig
from memory_os.core.interfaces import IMemoryOSConfig
from memory_os.core.repository import MemoryRepository
from memory_os.core.storage import FileSystemMemoryStorage


class MemoryHistory:
    """
    Read-only 'git log' / 'git show' style view over events.jsonl and
    archived_nodes.jsonl — the event-sourced history Memory OS already
    keeps for every node (memory.node.proposed / verified / deprecated,
    see LifecycleManager).

    This is the narrow, adopted kernel of RFC-0002 (Git Memory Chain): the
    RFC's own diagnosis — "memory should be legible history, not just
    current state" — is already true of this project's nodes.jsonl/
    edges.jsonl/events.jsonl design. What was missing was a readable view
    over it, not a new git-backed storage engine. Everything else RFC-0002
    proposed (hash-chained events, branch-per-agent, a merge engine,
    distributed/public memory repositories) was rejected for this project.
    The RFC itself was retired after its analysis was absorbed into
    docs/encyclopedia/roadmap.md's "Git Memory Chain (RFC-0002)" section,
    which also lists the concrete follow-on phases (node-level
    confidence/eval-gate, migrating onto RelationPatchStore, ...) this
    module doesn't cover yet.
    """

    def __init__(
        self,
        config: Optional[IMemoryOSConfig] = None,
        repository: Optional[MemoryRepository] = None,
    ):
        self.config = config or MemoryOSConfig()
        self.storage = FileSystemMemoryStorage()
        self.repository = repository or MemoryRepository(self.storage, self.config)

    def _load_events(self) -> List[Dict[str, Any]]:
        return self.storage.load_jsonl(self.config.memory_dir / "events.jsonl")

    def _load_archived_nodes(self) -> List[Dict[str, Any]]:
        return self.storage.load_jsonl(self.config.memory_dir / "archived_nodes.jsonl")

    def _load_edges(self) -> List[Dict[str, Any]]:
        return self.storage.load_jsonl(self.config.memory_dir / "edges.jsonl")

    def _load_archived_edges(self) -> List[Dict[str, Any]]:
        archived_path = self.config.memory_dir / "archived_edges.jsonl"
        if not self.storage.exists(archived_path):
            return []
        return self.storage.load_jsonl(archived_path)

    def log(self, node_id: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Chronological event history, optionally scoped to one node_id —
        the 'git log' view. Most recent last, matching events.jsonl's own
        append order; `limit` keeps only the most recent N if given."""
        events = self._load_events()
        if node_id:
            events = [e for e in events if e.get("node_id") == node_id]
        events.sort(key=lambda e: str(e.get("timestamp", "")))
        if limit:
            events = events[-limit:]
        return events

    def show(self, node_id: str) -> Dict[str, Any]:
        """One node's full story — current state (if still active),
        archived state (if pruned/superseded), and every event ever
        recorded against it. The 'git show' view."""
        current = next((n for n in self.repository.get_nodes() if n.id == node_id), None)
        archived = next((n for n in self._load_archived_nodes() if n.get("id") == node_id), None)
        history = self.log(node_id=node_id)
        edges = self._load_edges() + self._load_archived_edges()
        replacement_edges = [
            edge for edge in edges
            if edge.get("type") in {"overrides", "refutes", "supersedes"}
        ]
        replaced_by = sorted(
            {
                str(edge.get("source", ""))
                for edge in replacement_edges
                if edge.get("target") == node_id and edge.get("source")
            }
        )
        replaces = sorted(
            {
                str(edge.get("target", ""))
                for edge in replacement_edges
                if edge.get("source") == node_id and edge.get("target")
            }
        )

        superseding_edges = [
            edge for edge in replacement_edges
            if edge.get("target") == node_id and edge.get("source")
        ]
        superseded_by_details = []
        if superseding_edges:
            summaries = {n.id: n.summary for n in self.repository.get_nodes()}
            for n in self._load_archived_nodes():
                summaries.setdefault(n.get("id"), n.get("summary", ""))
            for edge in superseding_edges:
                source_id = edge.get("source")
                superseded_by_details.append({
                    "id": source_id,
                    "summary": summaries.get(source_id, ""),
                    "reason": edge.get("reason", "")
                })

        return {
            "node_id": node_id,
            "found": current is not None or archived is not None,
            "current": current.to_dict() if current else None,
            "archived": archived,
            "history": history,
            "replaced_by": replaced_by,
            "replaces": replaces,
            "superseded_by_details": superseded_by_details,
        }

    def revert(self, node_id: str, dry_run: bool = False) -> Dict[str, Any]:
        """
        Restore an archived (pruned/superseded) node back into the live
        graph as a fresh 'draft' — the inverse of LifecycleManager.prune().
        The 'rollback' piece of RFC-0002's Success Criteria that 'log'/
        'show' alone didn't cover. Deliberately does not restore its old
        edges (those may point at nodes that have since changed too) —
        bringing the node back is one decision, re-linking it is another.
        """
        nodes_path = self.config.memory_dir / "nodes.jsonl"
        archived_path = self.config.memory_dir / "archived_nodes.jsonl"

        archived = self._load_archived_nodes()
        match = next((n for n in archived if n.get("id") == node_id), None)
        if match is None:
            return {"ok": False, "detail": f"'{node_id}' not found in archived_nodes.jsonl"}

        current_nodes = self.storage.load_jsonl(nodes_path)
        if any(n.get("id") == node_id for n in current_nodes):
            return {"ok": False, "detail": f"'{node_id}' already exists in nodes.jsonl — remove or rename it first"}

        if dry_run:
            return {"ok": True, "dry_run": True, "node_id": node_id, "would_restore": match}

        restored = dict(match)
        restored["status"] = "draft"
        restored["trust"] = "unverified"
        self.repository.upsert_node(restored)
        self.storage.save_jsonl(archived_path, [n for n in archived if n.get("id") != node_id])

        return {"ok": True, "dry_run": False, "node_id": node_id, "status": "draft"}
