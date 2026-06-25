from dataclasses import dataclass, field
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


_EDGE_OPERATIONS = {"upsert_edge", "delete_edge_soft"}
_NODE_OPERATIONS = {"upsert_node", "deprecate_node"}


class RelationPatchStore:
    """Manages the proposal, application, and rollback of relation patches."""

    def __init__(self, repository: Any, registry: Any = None):
        self.repository = repository
        # registry is a RelationContractRegistry; if None, contract checks are skipped.
        self.registry = registry
        self._patches: Dict[str, RelationPatch] = {p.id: p for p in repository.get_patches()}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_propose(self, patch: RelationPatch) -> None:
        """Raise PatchValidationError if the patch cannot be proposed."""
        if self.registry is None or patch.operation not in _EDGE_OPERATIONS:
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
        if self.registry is None or patch.operation not in _EDGE_OPERATIONS:
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

    def apply(self, patch_id: str) -> bool:
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

        from memory_os.core.models import MemoryNode, MemoryEdge

        if patch.operation == "upsert_edge":
            edge = MemoryEdge(
                source=patch.source,
                target=patch.target,
                type=patch.type,
                domain=patch.domain,
                confidence=patch.confidence,
                evidence=patch.evidence,
                reason=patch.reason,
            )
            self.repository._add_edge(edge)
        elif patch.operation == "upsert_node":
            from datetime import datetime
            node = MemoryNode(
                id=patch.target,  # for node patches, target carries the node ID
                type=patch.type,
                summary=patch.payload.get("summary", ""),
                evidence=patch.evidence,
                domain=patch.domain,
                trust="verified" if patch.confidence > 0.8 else "unverified",
                valid_from=datetime.utcnow().isoformat() + "Z"
            )
            self.repository._add_node(node)
        elif patch.operation == "delete_edge_soft":
            edges = self.repository.get_edges()
            new_edges = [
                e for e in edges
                if not (e.source == patch.source and e.target == patch.target and e.type == patch.type)
            ]
            self.repository._save_edges(new_edges)
        elif patch.operation == "deprecate_node":
            from datetime import datetime
            nodes = self.repository.get_nodes()
            for node in nodes:
                if node.id == patch.target:
                    node.status = "stale"
                    node.valid_until = datetime.utcnow().isoformat() + "Z"
            self.repository._save_nodes(nodes)

        patch.status = "applied"
        self.repository.save_patch(patch)
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

        patch.status = "rolled_back"
        self.repository.save_patch(patch)
        return True

    def get_patch(self, patch_id: str) -> Optional[RelationPatch]:
        return self._patches.get(patch_id)
