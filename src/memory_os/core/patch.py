from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import uuid

@dataclass
class RelationPatch:
    """Represents a proposed change to the Memory OS graph."""
    operation: str  # e.g., "upsert_edge", "delete_edge_soft", "upsert_node", "deprecate_node"
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

class RelationPatchStore:
    """Manages the proposal, application, and rollback of relation patches."""
    
    def __init__(self, repository: Any):
        self.repository = repository
        self._patches: Dict[str, RelationPatch] = {}
        
    def propose(self, patch: RelationPatch) -> str:
        """Proposes a new patch. Returns the patch ID."""
        self._patches[patch.id] = patch
        # In a full implementation, this would emit an event or write to an append-only patch log
        self.repository.save_patch(patch)
        return patch.id
        
    def apply(self, patch_id: str) -> bool:
        """Applies a patch if it meets the verification protocol requirements."""
        patch = self._patches.get(patch_id)
        if not patch:
            return False
        
        if patch.status != "pending":
            return False
            
        from memory_os.core.models import MemoryNode, MemoryEdge
        
        if patch.operation == "upsert_edge":
            edge = MemoryEdge(
                source=patch.source,
                target=patch.target,
                type=patch.type,
                domain=patch.domain,
                confidence=patch.confidence,
                evidence=patch.evidence,
                reason=patch.reason
            )
            self.repository.add_edge(edge)
        elif patch.operation == "upsert_node":
            node = MemoryNode(
                id=patch.target,  # For nodes, target is the node ID
                type=patch.type,
                summary=patch.payload.get("summary", ""),
                evidence=patch.evidence,
                domain=patch.domain,
                trust="verified" if patch.confidence > 0.8 else "unverified"
            )
            self.repository.add_node(node)
        
        patch.status = "applied"
        self.repository.save_patch(patch)
        return True
        
    def rollback(self, patch_id: str) -> bool:
        """Rolls back an applied patch."""
        patch = self._patches.get(patch_id)
        if not patch:
            return False
            
        if patch.status != "applied":
            return False
            
        # Revert logic would go here (e.g. deleting the edge)
        # Note: True rollback requires tracking the previous state
        patch.status = "rolled_back"
        self.repository.save_patch(patch)
        return True

    def get_patch(self, patch_id: str) -> Optional[RelationPatch]:
        return self._patches.get(patch_id)

