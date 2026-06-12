import ast
import re
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Tuple
from pathlib import Path

from memory_os.core.patch import RelationPatch

class IDomainAdapter(ABC):
    """Abstract interface for Domain Adapters that convert domain-specific data into graph patches."""
    
    @abstractmethod
    def get_domain_name(self) -> str:
        pass

    @abstractmethod
    def parse_to_patches(self, resource_uri: str, content: Any, protocol_level: int = 4) -> List[RelationPatch]:
        """Convert a domain resource into a series of RelationPatches."""
        pass

class CodebaseDomainAdapter(IDomainAdapter):
    """Adapter for parsing Python code into AST-based Memory Nodes and Edges."""
    
    def get_domain_name(self) -> str:
        return "codebase"

    def parse_to_patches(self, resource_uri: str, content: Any, protocol_level: int = 4) -> List[RelationPatch]:
        if not isinstance(content, str):
            return []
            
        patches = []
        file_node_id = f"file:{resource_uri}"
        
        # 1. Upsert File Node
        patches.append(RelationPatch(
            operation="upsert_node",
            source="",
            target=file_node_id,
            type="file",
            domain=self.get_domain_name(),
            confidence=1.0,
            evidence=[resource_uri],
            reason="Domain adapter parsing",
            created_by_protocol=protocol_level,
            required_verification_protocol=protocol_level,
            payload={"summary": f"Code file {resource_uri}", "file_path": resource_uri}
        ))
        
        if resource_uri.endswith(".py"):
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    # Classes
                    if isinstance(node, ast.ClassDef):
                        class_id = f"class:{node.name}"
                        patches.append(self._create_node_patch(class_id, "class", f"Class {node.name}", resource_uri, protocol_level))
                        patches.append(self._create_edge_patch(file_node_id, class_id, "contains", resource_uri, protocol_level))
                    # Functions
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        func_id = f"function:{node.name}"
                        patches.append(self._create_node_patch(func_id, "function", f"Function {node.name}", resource_uri, protocol_level))
                        patches.append(self._create_edge_patch(file_node_id, func_id, "contains", resource_uri, protocol_level))
                    # Imports
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            dep = alias.name.split(".")[0]
                            dep_id = f"module:{dep}"
                            patches.append(self._create_edge_patch(file_node_id, dep_id, "depends_on", resource_uri, protocol_level))
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        dep = node.module.split(".")[0]
                        dep_id = f"module:{dep}"
                        patches.append(self._create_edge_patch(file_node_id, dep_id, "depends_on", resource_uri, protocol_level))
            except SyntaxError:
                pass
                
        return patches

    def _create_node_patch(self, node_id: str, node_type: str, summary: str, uri: str, protocol: int) -> RelationPatch:
        return RelationPatch(
            operation="upsert_node",
            source="",
            target=node_id,
            type=node_type,
            domain=self.get_domain_name(),
            confidence=0.9,
            evidence=[uri],
            reason="AST parsed",
            created_by_protocol=protocol,
            required_verification_protocol=protocol,
            payload={"summary": summary}
        )

    def _create_edge_patch(self, source: str, target: str, rel_type: str, uri: str, protocol: int) -> RelationPatch:
        return RelationPatch(
            operation="upsert_edge",
            source=source,
            target=target,
            type=rel_type,
            domain=self.get_domain_name(),
            confidence=0.9,
            evidence=[uri],
            reason="AST parsed",
            created_by_protocol=protocol,
            required_verification_protocol=protocol
        )
