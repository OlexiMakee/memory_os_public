from dataclasses import dataclass, field
from typing import List, Dict, Optional

@dataclass
class RelationContract:
    """Defines rules and permissions for a specific relation type in the graph."""
    layer: str
    default_protocol_level: int
    deterministic: bool
    min_create_protocol: int
    min_verify_protocol: int
    source_types: List[str] = field(default_factory=list)
    target_types: List[str] = field(default_factory=list)


class RelationContractRegistry:
    """Central registry of all allowed relation contracts."""
    
    def __init__(self):
        self._contracts: Dict[str, RelationContract] = {}
        self._initialize_defaults()

    def _initialize_defaults(self):
        # Structural
        self.register("depends_on", RelationContract(
            layer="structural", default_protocol_level=0, deterministic=True,
            min_create_protocol=0, min_verify_protocol=0
        ))
        
        # Operational
        self.register("reads_from", RelationContract(
            layer="operational", default_protocol_level=3, deterministic=True,
            min_create_protocol=0, min_verify_protocol=3
        ))
        self.register("writes_to", RelationContract(
            layer="operational", default_protocol_level=4, deterministic=True,
            min_create_protocol=0, min_verify_protocol=3
        ))
        
        # Workflow
        self.register("triggers", RelationContract(
            layer="workflow", default_protocol_level=6, deterministic=False,
            min_create_protocol=5, min_verify_protocol=6
        ))
        
        # Causal
        self.register("caused_by", RelationContract(
            layer="causal", default_protocol_level=8, deterministic=False,
            min_create_protocol=7, min_verify_protocol=8
        ))
        self.register("fixed_by", RelationContract(
            layer="causal", default_protocol_level=8, deterministic=False,
            min_create_protocol=7, min_verify_protocol=8
        ))
        self.register("refutes", RelationContract(
            layer="causal", default_protocol_level=8, deterministic=False,
            min_create_protocol=7, min_verify_protocol=8
        ))
        self.register("overrides", RelationContract(
            layer="causal", default_protocol_level=8, deterministic=False,
            min_create_protocol=7, min_verify_protocol=8
        ))
        self.register("strategic_consequence", RelationContract(
            layer="analytical", default_protocol_level=10, deterministic=False,
            min_create_protocol=9, min_verify_protocol=10
        ))

    def register(self, relation_type: str, contract: RelationContract):
        self._contracts[relation_type] = contract

    def get_contract(self, relation_type: str) -> Optional[RelationContract]:
        return self._contracts.get(relation_type)

    def validate_creation(self, relation_type: str, agent_protocol_level: int) -> bool:
        contract = self.get_contract(relation_type)
        if not contract:
            return False
        return agent_protocol_level >= contract.min_create_protocol

    def validate_verification(self, relation_type: str, agent_protocol_level: int) -> bool:
        contract = self.get_contract(relation_type)
        if not contract:
            return False
        return agent_protocol_level >= contract.min_verify_protocol
