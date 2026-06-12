from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Dict, Any, Optional

class NodeType(str, Enum):
    RULE = "rule"
    FACT = "fact"
    VARIABLE = "variable"
    CONNECTOR = "connector"
    CONFIG = "config"
    POLICY = "policy"
    MODULE_CLUSTER = "module_cluster"  # structural cluster of related files (inferred)

class EdgeType(str, Enum):
    DEPENDS_ON = "depends_on"
    TRIGGERS = "triggers"
    REFUTES = "refutes"
    OVERRIDES = "overrides"
    CONFIGURES = "configures"
    SECURES = "secures"
    CONTAINS = "contains"  # module_cluster -> code_file

@dataclass
class MemoryNode:
    id: str
    type: str  # Kept as str to allow dynamic serialization easily, but validated via NodeType
    summary: str
    evidence: List[str]
    status: str = "draft"
    freshness: str = ""
    trust: str = "unverified"
    related_nodes: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)  # optional labels for search/triage filtering

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryNode":
        return cls(
            id=data.get("id", ""),
            type=data.get("type", ""),
            summary=data.get("summary", ""),
            evidence=data.get("evidence", []),
            status=data.get("status", "draft"),
            freshness=data.get("freshness", ""),
            trust=data.get("trust", "unverified"),
            related_nodes=data.get("related_nodes", []),
            tags=data.get("tags", []),
        )
        
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class MemoryEdge:
    source: str
    target: str
    type: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryEdge":
        return cls(
            source=data.get("source", ""),
            target=data.get("target", ""),
            type=data.get("type", "")
        )
        
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class TaskCapsule:
    timestamp: str
    task: str
    workflow: str
    step: str
    files_modified: List[str]
    files_viewed: List[str]
    context_tokens: int
    tools_used: List[str]
    hurdles_regression: str
    resolution: str
    lessons_learned: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskCapsule":
        return cls(
            timestamp=data.get("timestamp", ""),
            task=data.get("task", ""),
            workflow=data.get("workflow", ""),
            step=data.get("step", ""),
            files_modified=data.get("files_modified", []),
            files_viewed=data.get("files_viewed", []),
            context_tokens=data.get("context_tokens", 0),
            tools_used=data.get("tools_used", []),
            hurdles_regression=data.get("hurdles_regression", ""),
            resolution=data.get("resolution", ""),
            lessons_learned=data.get("lessons_learned", "")
        )
        
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
