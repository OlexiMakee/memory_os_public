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


# Protocol level semantics (P0–P13):
#
#  P0–P1   structural     — deterministic, inferred from static analysis (dependencies, containment)
#  P2–P4   operational    — inferred from runtime or config parsing (reads/writes, configuration, access control)
#  P5–P6   workflow       — inferred from execution traces or orchestration graphs (triggers)
#  P7–P8   causal         — requires reasoning over evidence chains (cause/effect, fixes, contradictions)
#  P9–P10  analytical     — requires cross-domain synthesis (strategic consequences)
#  P11–P13 cross-domain   — requires multi-agent deliberation and human verification


class RelationContractRegistry:
    """Central registry of all allowed relation contracts."""

    def __init__(self):
        self._contracts: Dict[str, RelationContract] = {}
        self._initialize_defaults()

    def _initialize_defaults(self):
        # --- Structural (P0–P1) ---
        self.register("depends_on", RelationContract(
            layer="structural", default_protocol_level=0, deterministic=True,
            min_create_protocol=0, min_verify_protocol=0,
        ))
        self.register("contains", RelationContract(
            layer="structural", default_protocol_level=1, deterministic=True,
            min_create_protocol=0, min_verify_protocol=0,
        ))

        # --- Operational (P2–P4) ---
        self.register("configures", RelationContract(
            layer="operational", default_protocol_level=2, deterministic=True,
            min_create_protocol=1, min_verify_protocol=2,
        ))
        self.register("reads_from", RelationContract(
            layer="operational", default_protocol_level=3, deterministic=True,
            min_create_protocol=0, min_verify_protocol=3,
        ))
        self.register("writes_to", RelationContract(
            layer="operational", default_protocol_level=4, deterministic=True,
            min_create_protocol=0, min_verify_protocol=3,
        ))
        self.register("secures", RelationContract(
            layer="operational", default_protocol_level=4, deterministic=True,
            min_create_protocol=3, min_verify_protocol=4,
        ))

        # --- Workflow (P5–P6) ---
        self.register("triggers", RelationContract(
            layer="workflow", default_protocol_level=6, deterministic=False,
            min_create_protocol=5, min_verify_protocol=6,
        ))

        # --- Causal (P7–P8) ---
        self.register("caused_by", RelationContract(
            layer="causal", default_protocol_level=8, deterministic=False,
            min_create_protocol=7, min_verify_protocol=8,
        ))
        self.register("fixed_by", RelationContract(
            layer="causal", default_protocol_level=8, deterministic=False,
            min_create_protocol=7, min_verify_protocol=8,
        ))
        self.register("refutes", RelationContract(
            layer="causal", default_protocol_level=8, deterministic=False,
            min_create_protocol=7, min_verify_protocol=8,
        ))
        self.register("overrides", RelationContract(
            layer="causal", default_protocol_level=8, deterministic=False,
            min_create_protocol=7, min_verify_protocol=8,
        ))

        # --- Analytical (P9–P10) ---
        self.register("strategic_consequence", RelationContract(
            layer="analytical", default_protocol_level=10, deterministic=False,
            min_create_protocol=9, min_verify_protocol=10,
        ))

        # --- Cross-domain (P11–P13) ---
        self.register("cross_domain_dependency", RelationContract(
            layer="cross_domain", default_protocol_level=11, deterministic=False,
            min_create_protocol=11, min_verify_protocol=12,
        ))
        self.register("emergent_pattern", RelationContract(
            layer="cross_domain", default_protocol_level=12, deterministic=False,
            min_create_protocol=12, min_verify_protocol=13,
        ))
        self.register("architectural_decision", RelationContract(
            layer="cross_domain", default_protocol_level=13, deterministic=False,
            min_create_protocol=12, min_verify_protocol=13,
        ))

    def register(self, relation_type: str, contract: RelationContract) -> None:
        self._contracts[relation_type] = contract

    def get_contract(self, relation_type: str) -> Optional[RelationContract]:
        return self._contracts.get(relation_type)

    def all_relation_types(self) -> List[str]:
        return list(self._contracts.keys())

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
