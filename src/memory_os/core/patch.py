from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
import uuid


class PatchValidationError(Exception):
    """Raised when a RelationPatch fails contract validation."""


@dataclass
class RelationPatch:
    """Represents a proposed change to the Memory OS graph."""
    operation: str  # "upsert_edge", "delete_edge_soft", "upsert_node", "deprecate_node"
    source: str
    target: str
    type: str
    domain: str
    confidence: float
    evidence: List[str]
    reason: str
    created_by_protocol: int
    required_verification_protocol: int
    payload: Dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "pending"  # pending, applied, rejected, rolled_back

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RelationPatch":
        return cls(
            operation=data.get("operation", ""),
            source=data.get("source", ""),
            target=data.get("target", ""),
            type=data.get("type", ""),
            domain=data.get("domain", ""),
            confidence=float(data.get("confidence", 0.0) or 0.0),
            evidence=data.get("evidence", []),
            reason=data.get("reason", ""),
            created_by_protocol=int(data.get("created_by_protocol", 0) or 0),
            required_verification_protocol=int(data.get("required_verification_protocol", 0) or 0),
            payload=data.get("payload", {}),
            id=data.get("id") or str(uuid.uuid4()),
            status=data.get("status", "pending")
        )


_EDGE_OPERATIONS = {"upsert_edge", "delete_edge_soft", "replace_edges"}
_NODE_OPERATIONS = {"upsert_node", "deprecate_node", "update_node", "replace_nodes"}
_EVENT_OPERATIONS = {"replace_events"}
_CONTRACT_EDGE_OPERATIONS = {"upsert_edge", "delete_edge_soft"}


class RelationPatchStore:
    """Manages the proposal, application, and rollback of relation patches."""

    def __init__(self, repository: Any, registry: Any = None):
        self.repository = repository
        if registry is None:
            from memory_os.core.registry import RelationContractRegistry
            registry = RelationContractRegistry()
        self.registry = registry
        self._patches: Dict[str, RelationPatch] = {p.id: p for p in repository.get_patches()}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_propose(self, patch: RelationPatch) -> None:
        """Raise PatchValidationError if the patch cannot be proposed."""
        if self.registry is None or patch.operation not in _CONTRACT_EDGE_OPERATIONS:
            return

        contract = self.registry.get_contract(patch.type)
        if contract is None:
            raise PatchValidationError(
                f"Unknown relation type '{patch.type}'. "
                "Register it in RelationContractRegistry before proposing patches."
            )

        if patch.created_by_protocol < contract.min_create_protocol:
            raise PatchValidationError(
                f"Patch for '{patch.type}' requires protocol >= {contract.min_create_protocol} "
                f"to create, but agent has protocol {patch.created_by_protocol}."
            )

    def _validate_apply(self, patch: RelationPatch) -> None:
        """Raise PatchValidationError if the patch cannot be applied."""
        if self.registry is None or patch.operation not in _CONTRACT_EDGE_OPERATIONS:
            return

        contract = self.registry.get_contract(patch.type)
        if contract is None:
            raise PatchValidationError(
                f"Unknown relation type '{patch.type}'. Cannot apply patch."
            )

        if patch.required_verification_protocol < contract.min_verify_protocol:
            raise PatchValidationError(
                f"Patch for '{patch.type}' requires verification protocol >= "
                f"{contract.min_verify_protocol}, but patch declares "
                f"{patch.required_verification_protocol}."
            )

    def _snapshot_before_apply(self, patch: RelationPatch) -> Dict[str, Any]:
        if patch.operation in _NODE_OPERATIONS:
            get_nodes = getattr(self.repository, "get_local_nodes", self.repository.get_nodes)
            return {
                "nodes": [
                    node.to_dict() if hasattr(node, "to_dict") else dict(node)
                    for node in get_nodes()
                ]
            }
        if patch.operation in _EDGE_OPERATIONS:
            return {
                "edges": [
                    edge.to_dict() if hasattr(edge, "to_dict") else dict(edge)
                    for edge in self.repository.get_edges()
                ]
            }
        if patch.operation in _EVENT_OPERATIONS:
            return {"events": [dict(event) for event in self.repository.get_events()]}
        return {}

    def _apply_rollback_snapshot(self, patch: RelationPatch, snapshot: Dict[str, Any]) -> bool:
        if not snapshot:
            return False

        if "nodes" in snapshot:
            rollback_patch = self.repository._make_patch(
                operation="replace_nodes",
                target="memory/nodes.jsonl",
                payload={"nodes": snapshot["nodes"]},
                reason=f"rollback patch {patch.id}",
            )
        elif "edges" in snapshot:
            rollback_patch = self.repository._make_patch(
                operation="replace_edges",
                target="memory/edges.jsonl",
                payload={"edges": snapshot["edges"]},
                reason=f"rollback patch {patch.id}",
            )
        elif "events" in snapshot:
            rollback_patch = self.repository._make_patch(
                operation="replace_events",
                target="memory/events.jsonl",
                payload={"events": snapshot["events"]},
                reason=f"rollback patch {patch.id}",
            )
        else:
            return False

        from memory_os.core.timecode import now_local_iso

        applied = self.repository.apply_patch(rollback_patch, events=[{
            "event": "memory.patch.rolled_back",
            "node_id": patch.target or patch.source,
            "claim": f"Rolled back relation patch {patch.id}",
            "evidence": patch.evidence,
            "validator": "relation_patch_store",
            "status": "accepted",
            "patch_id": patch.id,
            "rolled_back_patch_id": patch.id,
            "timestamp": now_local_iso(getattr(self.repository, "config", None)),
        }])
        return applied

    def _load_archived_rollback_snapshot(self, patch: RelationPatch) -> Optional[Dict[str, Any]]:
        payload = patch.payload if isinstance(patch.payload, dict) else {}
        archive_ref = payload.get("_rollback_archive")
        if not archive_ref:
            return None
        archive_path = Path(str(archive_ref))
        if not archive_path.is_absolute():
            archive_path = self.repository.config.root_dir / archive_path
        if not archive_path.exists():
            return None
        try:
            for line in archive_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if row.get("patch_id") != patch.id:
                    continue
                snapshot = row.get("rollback")
                if isinstance(snapshot, dict):
                    return snapshot
        except (OSError, json.JSONDecodeError):
            return None
        return None

    def _patch_event(self, patch: RelationPatch) -> Dict[str, Any]:
        from memory_os.core.timecode import now_local_iso
        return {
            "event": f"memory.patch.{patch.operation}",
            "node_id": patch.target or patch.source,
            "claim": patch.reason or f"Applied relation patch {patch.id}",
            "evidence": patch.evidence,
            "validator": "relation_patch_store",
            "status": "accepted",
            "patch_id": patch.id,
            "timestamp": now_local_iso(getattr(self.repository, "config", None)),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def propose(self, patch: RelationPatch) -> str:
        """Validate and record a new patch. Returns the patch ID.

        Raises PatchValidationError if the proposing agent's protocol level is
        below the contract's min_create_protocol for this relation type.
        """
        self._validate_propose(patch)
        self._patches[patch.id] = patch
        self.repository.save_patch(patch)
        return patch.id

    def apply(self, patch_id: str, events: Optional[List[Dict[str, Any]]] = None) -> bool:
        """Apply a pending patch after verifying it meets the contract's verification threshold.

        Raises PatchValidationError if required_verification_protocol is below
        the contract's min_verify_protocol for this relation type.
        Returns False if the patch is not found or is not in pending state.
        """
        patch = self._patches.get(patch_id)
        if not patch:
            return False

        if patch.status != "pending":
            return False

        self._validate_apply(patch)
        snapshot = self._snapshot_before_apply(patch)
        if snapshot:
            patch.payload["_rollback"] = snapshot

        all_events = [self._patch_event(patch)]
        if events:
            all_events.extend(events)
        applied = self.repository.apply_patch(patch, events=all_events)
        if not applied:
            return False

        patch.status = "applied"
        self.repository.save_patch(patch)
        return True

    def apply_many(self, patch_ids: List[str], events: Optional[List[Dict[str, Any]]] = None) -> bool:
        """Apply multiple pending patches and refresh derived indexes once.

        This keeps multi-file graph mutations closer together without changing
        the underlying JSONL source-of-truth format.
        """
        patches = []
        for patch_id in patch_ids:
            patch = self._patches.get(patch_id)
            if not patch or patch.status != "pending":
                return False
            self._validate_apply(patch)
            patches.append(patch)

        for idx, patch in enumerate(patches):
            snapshot = self._snapshot_before_apply(patch)
            if snapshot:
                patch.payload["_rollback"] = snapshot
            patch_events = [self._patch_event(patch)]
            if events and idx == len(patches) - 1:
                patch_events.extend(events)
            applied = self.repository.apply_patch(patch, events=patch_events, sync=False)
            if not applied:
                return False
            patch.status = "applied"
            self.repository.save_patch(patch)

        from memory_os.modules.search import MemorySearcher
        searcher = MemorySearcher(config=self.repository.config, repository=self.repository)
        for patch in patches:
            searcher.incremental_sync(patch)
        return True

    def rollback(self, patch_id: str) -> bool:
        """Mark an applied patch as rolled back.

        Note: structural rollback (undoing the persisted edge/node) requires
        tracking prior state and is not yet implemented.
        """
        patch = self._patches.get(patch_id)
        if not patch:
            return False

        if patch.status != "applied":
            return False

        snapshot = patch.payload.get("_rollback")
        if not isinstance(snapshot, dict):
            snapshot = self._load_archived_rollback_snapshot(patch)
        if not isinstance(snapshot, dict):
            return False
        if not self._apply_rollback_snapshot(patch, snapshot):
            return False
        patch.status = "rolled_back"
        self.repository.save_patch(patch)
        return True

    def get_patch(self, patch_id: str) -> Optional[RelationPatch]:
        return self._patches.get(patch_id)
