from abc import ABC, abstractmethod
import ast
from collections import defaultdict
from dataclasses import dataclass
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from memory_os.core.patch import RelationPatch
from memory_os.core.safe_id import node_id_slug


@dataclass
class DomainIngestResult:
    resource_uri: str
    domain: str
    patch_ids: List[str]
    patch_count: int
    applied: bool
    dry_run: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource_uri": self.resource_uri,
            "domain": self.domain,
            "patch_ids": self.patch_ids,
            "patch_count": self.patch_count,
            "applied": self.applied,
            "dry_run": self.dry_run,
        }


class IDomainAdapter(ABC):
    """Abstract interface for Domain Adapters that convert domain-specific data into graph patches."""

    @abstractmethod
    def get_domain_name(self) -> str:
        pass

    def supports(self, resource_uri: str, content: Any = None) -> bool:
        return False

    @abstractmethod
    def extract_metadata(self, resource_uri: str, content: Any) -> Dict[str, Any]:
        """Extract domain-specific metadata (e.g. symbols, headers) for snapshot indexing."""
        pass

    @abstractmethod
    def parse_to_patches(self, resource_uri: str, content: Any, protocol_level: int = 4) -> List[RelationPatch]:
        """Convert a domain resource into a series of RelationPatches."""
        pass


class AstDomainAdapter(IDomainAdapter):
    """Adapter for parsing Python and JavaScript code into deterministic symbols."""

    GOD_NODE_TOP_N = 8
    CLUSTER_TOP_N = 6

    def get_domain_name(self) -> str:
        return "ast"

    def supports(self, resource_uri: str, content: Any = None) -> bool:
        return Path(resource_uri).suffix.lower() in {".py", ".js"}

    def extract_metadata(self, resource_uri: str, content: Any) -> Dict[str, Any]:
        if not isinstance(content, str):
            return {}

        meta: Dict[str, Any] = {}
        if resource_uri.endswith(".py"):
            try:
                tree = ast.parse(content)
                funcs = []
                classes = []
                imports = []
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        funcs.append(f"{node.name}:{node.lineno}")
                    elif isinstance(node, ast.ClassDef):
                        classes.append(f"{node.name}:{node.lineno}")
                    elif isinstance(node, ast.Import):
                        imports.extend(alias.name.split(".")[0] for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imports.append(node.module.split(".")[0])
                meta.update(
                    {
                        "functions": funcs[:30],
                        "classes": classes[:20],
                        "dependencies": sorted(set(imports))[:30],
                    }
                )

                routes = re.findall(r"@\w+_bp\.route\(['\"]([^'\"]+)['\"](?:,\s*methods=([^\)]*))?\)", content)
                if routes:
                    meta["routes"] = [f"{path} {methods or '[GET]'}" for path, methods in routes[:30]]
            except SyntaxError:
                pass

        elif resource_uri.endswith(".js"):
            funcs = re.findall(r"\b(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_]+)\s*\(", content)
            classes = re.findall(r"\b(?:export\s+)?class\s+([A-Za-z0-9_]+)\b", content)
            imports = re.findall(r"\bimport\b[^;]*?\bfrom\s+['\"]([^'\"]+)['\"]", content)
            meta.update(
                {
                    "functions": funcs[:30],
                    "classes": classes[:20],
                    "dependencies": imports[:30],
                }
                )

        if meta:
            meta["domain"] = self.get_domain_name()
        return meta

    def build_reverse_dependency_map(
        self,
        items_by_file: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Set[str]]:
        all_files = list(items_by_file.keys())
        reverse: Dict[str, Set[str]] = {file: set() for file in all_files}
        for src_file, item in items_by_file.items():
            for dependency in item.get("meta", {}).get("dependencies", []):
                for other_file in all_files:
                    if src_file == other_file:
                        continue
                    if self.dependency_matches_file(str(dependency), other_file, include_path_parts=False):
                        reverse[other_file].add(src_file)
                        break
        return reverse

    def traverse_dependencies(
        self,
        start_files: Set[str],
        depth: int,
        items_by_file: Dict[str, Dict[str, Any]],
    ) -> Set[str]:
        visited = set(start_files)
        current_level = set(start_files)

        for _ in range(depth):
            next_level: Set[str] = set()
            for filepath in current_level:
                item = items_by_file.get(filepath)
                if not item:
                    continue
                for dependency in item.get("meta", {}).get("dependencies", []):
                    for other_file in items_by_file:
                        if self.dependency_matches_file(str(dependency), other_file, include_path_parts=True):
                            if other_file not in visited:
                                next_level.add(other_file)
                                visited.add(other_file)
            current_level = next_level
            if not current_level:
                break
        return visited

    def traverse_dependents(
        self,
        start_files: Set[str],
        depth: int,
        reverse_map: Dict[str, Set[str]],
    ) -> Set[str]:
        visited = set(start_files)
        current_level = set(start_files)
        for _ in range(depth):
            next_level: Set[str] = set()
            for filepath in current_level:
                for dependent in reverse_map.get(filepath, set()):
                    if dependent not in visited:
                        next_level.add(dependent)
                        visited.add(dependent)
            current_level = next_level
            if not current_level:
                break
        return visited

    def dependency_matches_file(self, dependency: str, filepath: str, include_path_parts: bool) -> bool:
        dependency_lower = dependency.lower()
        other_path = Path(filepath)
        other_stem = other_path.stem.lower()
        other_mod = other_path.with_suffix("").as_posix().replace("/", ".").lower()
        if dependency_lower == other_stem or dependency_lower == other_mod or other_mod.endswith("." + dependency_lower):
            return True
        return include_path_parts and dependency_lower in other_path.as_posix().lower().split("/")

    def resolve_dependency_to_file(self, dependency: str, all_files: List[str]) -> Optional[str]:
        for filepath in all_files:
            if self.dependency_matches_file(dependency, filepath, include_path_parts=False):
                return filepath
        return None

    def build_dependency_graph(
        self,
        items: List[Dict[str, Any]],
    ) -> tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
        all_files = [item["meta"]["file"] for item in items]
        forward: Dict[str, Set[str]] = defaultdict(set)
        reverse: Dict[str, Set[str]] = defaultdict(set)

        for item in items:
            src = item["meta"]["file"]
            for dependency in item["meta"].get("dependencies", []):
                target = self.resolve_dependency_to_file(str(dependency), all_files)
                if target and target != src:
                    forward[src].add(target)
                    reverse[target].add(src)

        return dict(forward), dict(reverse)

    def compute_god_nodes(
        self,
        reverse: Dict[str, Set[str]],
        items: List[Dict[str, Any]],
        top_n: int = GOD_NODE_TOP_N,
    ) -> List[Dict[str, Any]]:
        in_degree = {
            item["meta"]["file"]: len(reverse.get(item["meta"]["file"], set()))
            for item in items
        }
        ranked = sorted(in_degree.items(), key=lambda item: item[1], reverse=True)
        results = []
        for filepath, degree in ranked[:top_n]:
            if degree == 0:
                break
            item = next((candidate for candidate in items if candidate["meta"]["file"] == filepath), None)
            meta = item["meta"] if item else {}
            results.append(
                {
                    "file": filepath,
                    "in_degree": degree,
                    "layer": meta.get("layer", "unknown"),
                    "classes": meta.get("classes", []),
                    "functions": meta.get("functions", []),
                    "routes": meta.get("routes", []),
                    "dependents": sorted(reverse.get(filepath, set())),
                    "trust": "extracted",
                }
            )
        return results

    def compute_clusters(
        self,
        items: List[Dict[str, Any]],
        forward: Dict[str, Set[str]],
        top_n: int = CLUSTER_TOP_N,
    ) -> List[Dict[str, Any]]:
        dir_files: Dict[str, List[str]] = defaultdict(list)
        for item in items:
            filepath = item["meta"]["file"]
            top_dir = Path(filepath).parts[0] if len(Path(filepath).parts) > 1 else "root"
            dir_files[top_dir].append(filepath)

        clusters = []
        for dir_name, files in sorted(dir_files.items(), key=lambda item: -len(item[1])):
            if len(files) < 2:
                continue
            file_set = set(files)
            internal_edges = sum(len(forward.get(filepath, set()) & file_set) for filepath in files)
            clusters.append(
                {
                    "name": dir_name,
                    "files": sorted(files),
                    "file_count": len(files),
                    "internal_edges": internal_edges,
                    "trust": "inferred",
                }
            )
        return sorted(clusters, key=lambda item: item["internal_edges"], reverse=True)[:top_n]

    def cluster_node_id(self, cluster_name: str) -> str:
        return f"structure.cluster.{node_id_slug(cluster_name)}"

    def cluster_to_node(self, cluster: Dict[str, Any], generated_at: str) -> Dict[str, Any]:
        return {
            "id": self.cluster_node_id(str(cluster["name"])),
            "type": "module_cluster",
            "summary": (
                f"Module cluster '{cluster['name']}': "
                f"{cluster['file_count']} files, "
                f"{cluster['internal_edges']} internal import edges. "
                f"Files: {', '.join(cluster['files'][:6])}"
                + (" ..." if len(cluster["files"]) > 6 else ".")
            ),
            "evidence": cluster["files"],
            "status": "verified",
            "freshness": generated_at,
            "trust": "inferred",
            "related_nodes": [],
            "tags": ["codebase", "module_cluster"],
            "domain": self.get_domain_name(),
        }

    def cluster_contains_edges(
        self,
        clusters: List[Dict[str, Any]],
        nodes: List[Dict[str, Any]],
        emitted_cluster_ids: Set[str],
        existing_edge_pairs: Set[tuple[str, str]],
    ) -> List[Dict[str, Any]]:
        new_edges = []
        for cluster in clusters:
            cluster_id = self.cluster_node_id(str(cluster["name"]))
            if cluster_id not in emitted_cluster_ids:
                continue
            cluster_files: Set[str] = set(cluster["files"])
            for node in nodes:
                nid = node.get("id", "")
                if nid == cluster_id:
                    continue
                node_evidence: Set[str] = set(node.get("evidence", []))
                if node_evidence & cluster_files:
                    key = (cluster_id, nid)
                    if key not in existing_edge_pairs:
                        new_edges.append(
                            {
                                "source": cluster_id,
                                "target": nid,
                                "type": "contains",
                                "confidence": 1.0,
                                "reason": "codebase-cluster-evidence",
                                "domain": self.get_domain_name(),
                                "evidence": [],
                            }
                        )
                        existing_edge_pairs.add(key)
        return new_edges

    def parse_to_patches(self, resource_uri: str, content: Any, protocol_level: int = 4) -> List[RelationPatch]:
        if not isinstance(content, str):
            return []

        patches = []
        file_node_id = self._file_node_id(resource_uri)

        patches.append(
            RelationPatch(
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
                payload={"summary": f"Code file {resource_uri}", "file_path": resource_uri},
            )
        )

        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    class_id = self._symbol_node_id("class", resource_uri, node.name)
                    patches.append(self._create_node_patch(class_id, "class", f"Class {node.name}", resource_uri, protocol_level))
                    patches.append(self._create_edge_patch(file_node_id, class_id, "contains", resource_uri, protocol_level))
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func_id = self._symbol_node_id("function", resource_uri, node.name)
                    patches.append(self._create_node_patch(func_id, "function", f"Function {node.name}", resource_uri, protocol_level))
                    patches.append(self._create_edge_patch(file_node_id, func_id, "contains", resource_uri, protocol_level))
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        dep = alias.name.split(".")[0]
                        dep_id = self._module_node_id(dep)
                        patches.append(self._create_node_patch(dep_id, "module", f"Module {dep}", resource_uri, protocol_level))
                        patches.append(self._create_edge_patch(file_node_id, dep_id, "depends_on", resource_uri, protocol_level))
                elif isinstance(node, ast.ImportFrom) and node.module:
                    dep = node.module.split(".")[0]
                    dep_id = self._module_node_id(dep)
                    patches.append(self._create_node_patch(dep_id, "module", f"Module {dep}", resource_uri, protocol_level))
                    patches.append(self._create_edge_patch(file_node_id, dep_id, "depends_on", resource_uri, protocol_level))
        except SyntaxError:
            pass

        return patches

    def _file_node_id(self, resource_uri: str) -> str:
        return f"file:{node_id_slug(resource_uri)}"

    def _symbol_node_id(self, kind: str, resource_uri: str, name: str) -> str:
        return f"{kind}:{node_id_slug(f'{resource_uri}:{name}')}"

    def _module_node_id(self, name: str) -> str:
        return f"module:{node_id_slug(name)}"

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
            payload={"summary": summary},
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
            required_verification_protocol=protocol,
        )


class GrepDomainAdapter(IDomainAdapter):
    """Adapter for deterministic text matching over plain-text resources."""

    TEXT_SUFFIXES = {".txt", ".md", ".rst", ".log"}

    def get_domain_name(self) -> str:
        return "grep"

    def supports(self, resource_uri: str, content: Any = None) -> bool:
        suffix = Path(resource_uri).suffix.lower()
        return suffix in self.TEXT_SUFFIXES or (suffix == "" and isinstance(content, str))

    def extract_metadata(self, resource_uri: str, content: Any) -> Dict[str, Any]:
        if not isinstance(content, str):
            return {}
        lines = content.splitlines()
        return {
            "line_count": len(lines),
            "nonempty_lines": sum(1 for line in lines if line.strip()),
            "domain": self.get_domain_name(),
        }

    def parse_to_patches(self, resource_uri: str, content: Any, protocol_level: int = 4) -> List[RelationPatch]:
        return []


class CodebaseDomainAdapter(IDomainAdapter):
    """Adapter that routes codebase resources through deterministic subadapters."""

    def __init__(self, ast_adapter: Optional[IDomainAdapter] = None, grep_adapter: Optional[IDomainAdapter] = None):
        self.ast_adapter = ast_adapter or AstDomainAdapter()
        self.grep_adapter = grep_adapter or GrepDomainAdapter()

    def get_domain_name(self) -> str:
        return "codebase"

    def supports(self, resource_uri: str, content: Any = None) -> bool:
        return self.ast_adapter.supports(resource_uri, content) or self.grep_adapter.supports(resource_uri, content)

    def extract_metadata(self, resource_uri: str, content: Any) -> Dict[str, Any]:
        adapter = self.ast_adapter if self.ast_adapter.supports(resource_uri, content) else self.grep_adapter
        meta = adapter.extract_metadata(resource_uri, content)
        if meta:
            meta.setdefault("domain", adapter.get_domain_name())
        return meta

    def build_reverse_dependency_map(
        self,
        items_by_file: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Set[str]]:
        return self.ast_adapter.build_reverse_dependency_map(items_by_file)

    def traverse_dependencies(
        self,
        start_files: Set[str],
        depth: int,
        items_by_file: Dict[str, Dict[str, Any]],
    ) -> Set[str]:
        return self.ast_adapter.traverse_dependencies(start_files, depth, items_by_file)

    def traverse_dependents(
        self,
        start_files: Set[str],
        depth: int,
        reverse_map: Dict[str, Set[str]],
    ) -> Set[str]:
        return self.ast_adapter.traverse_dependents(start_files, depth, reverse_map)

    def dependency_matches_file(self, dependency: str, filepath: str, include_path_parts: bool) -> bool:
        return self.ast_adapter.dependency_matches_file(dependency, filepath, include_path_parts)

    def resolve_dependency_to_file(self, dependency: str, all_files: List[str]) -> Optional[str]:
        return self.ast_adapter.resolve_dependency_to_file(dependency, all_files)

    def build_dependency_graph(
        self,
        items: List[Dict[str, Any]],
    ) -> tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
        return self.ast_adapter.build_dependency_graph(items)

    def compute_god_nodes(
        self,
        reverse: Dict[str, Set[str]],
        items: List[Dict[str, Any]],
        top_n: int = AstDomainAdapter.GOD_NODE_TOP_N,
    ) -> List[Dict[str, Any]]:
        return self.ast_adapter.compute_god_nodes(reverse, items, top_n=top_n)

    def compute_clusters(
        self,
        items: List[Dict[str, Any]],
        forward: Dict[str, Set[str]],
        top_n: int = AstDomainAdapter.CLUSTER_TOP_N,
    ) -> List[Dict[str, Any]]:
        return self.ast_adapter.compute_clusters(items, forward, top_n=top_n)

    def cluster_node_id(self, cluster_name: str) -> str:
        return self.ast_adapter.cluster_node_id(cluster_name)

    def cluster_to_node(self, cluster: Dict[str, Any], generated_at: str) -> Dict[str, Any]:
        return self.ast_adapter.cluster_to_node(cluster, generated_at)

    def cluster_contains_edges(
        self,
        clusters: List[Dict[str, Any]],
        nodes: List[Dict[str, Any]],
        emitted_cluster_ids: Set[str],
        existing_edge_pairs: Set[tuple[str, str]],
    ) -> List[Dict[str, Any]]:
        return self.ast_adapter.cluster_contains_edges(clusters, nodes, emitted_cluster_ids, existing_edge_pairs)

    def parse_to_patches(self, resource_uri: str, content: Any, protocol_level: int = 4) -> List[RelationPatch]:
        if self.ast_adapter.supports(resource_uri, content):
            return self.ast_adapter.parse_to_patches(resource_uri, content, protocol_level=protocol_level)
        return self.grep_adapter.parse_to_patches(resource_uri, content, protocol_level=protocol_level)


class DomainAdapterRegistry:
    """Small registry for deterministic domain adapters."""

    def __init__(self, adapters: Optional[Iterable[IDomainAdapter]] = None):
        self._adapters: Dict[str, IDomainAdapter] = {}
        for adapter in adapters or [CodebaseDomainAdapter()]:
            self.register(adapter)

    def register(self, adapter: IDomainAdapter) -> None:
        self._adapters[adapter.get_domain_name()] = adapter

    def get(self, domain_name: str) -> Optional[IDomainAdapter]:
        return self._adapters.get(domain_name)

    def require(self, domain_name: str) -> IDomainAdapter:
        adapter = self.get(domain_name)
        if adapter is None:
            raise KeyError(f"domain adapter not registered: {domain_name}")
        return adapter

    def select(self, resource_uri: str, content: Any = None) -> Optional[IDomainAdapter]:
        for adapter in self._adapters.values():
            if adapter.supports(resource_uri, content):
                return adapter
        return None

    def extract_metadata(self, resource_uri: str, content: Any) -> Dict[str, Any]:
        adapter = self.select(resource_uri, content)
        if adapter is None:
            return {}
        metadata = adapter.extract_metadata(resource_uri, content)
        if metadata:
            metadata.setdefault("domain", adapter.get_domain_name())
        return metadata

    def parse_to_patches(self, resource_uri: str, content: Any, protocol_level: int = 4) -> List[RelationPatch]:
        adapter = self.select(resource_uri, content)
        if adapter is None:
            return []
        return adapter.parse_to_patches(resource_uri, content, protocol_level=protocol_level)

    def all(self) -> List[IDomainAdapter]:
        return list(self._adapters.values())


class DomainAdapterIngestor:
    """Applies deterministic domain-adapter output through RelationPatchStore."""

    def __init__(self, repository: Any, registry: Optional[DomainAdapterRegistry] = None):
        self.repository = repository
        self.registry = registry or DomainAdapterRegistry()

    def ingest_resource(
        self,
        resource_uri: str,
        content: Any,
        protocol_level: int = 4,
        dry_run: bool = False,
    ) -> DomainIngestResult:
        adapter = self.registry.select(resource_uri, content)
        domain = adapter.get_domain_name() if adapter else ""
        patches = self.registry.parse_to_patches(resource_uri, content, protocol_level=protocol_level)
        if dry_run:
            return DomainIngestResult(
                resource_uri=resource_uri,
                domain=domain,
                patch_ids=[patch.id for patch in patches],
                patch_count=len(patches),
                applied=False,
                dry_run=True,
            )
        if not patches:
            return DomainIngestResult(
                resource_uri=resource_uri,
                domain=domain,
                patch_ids=[],
                patch_count=0,
                applied=True,
            )

        from memory_os.core.patch import RelationPatchStore

        store = RelationPatchStore(self.repository)
        patch_ids = [store.propose(patch) for patch in patches]
        applied = store.apply_many(patch_ids)
        return DomainIngestResult(
            resource_uri=resource_uri,
            domain=domain,
            patch_ids=patch_ids,
            patch_count=len(patch_ids),
            applied=applied,
        )

    def ingest_python_tree(
        self,
        source_root: Path,
        project_root: Path,
        protocol_level: int = 4,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        project_root = project_root.resolve()
        source_root = source_root.resolve()
        try:
            source_root.relative_to(project_root)
        except ValueError as exc:
            raise ValueError(f"source root must stay inside project root: {source_root}") from exc
        if not source_root.is_dir():
            raise ValueError(f"source root is not a directory: {source_root}")

        from memory_os.core.patch import RelationPatchStore
        from memory_os.core.timecode import now_local_iso

        files = sorted(path for path in source_root.rglob("*.py") if path.is_file())
        patches: List[RelationPatch] = []
        operations_planned = 0
        for path in files:
            resolved = path.resolve()
            try:
                resource_uri = resolved.relative_to(project_root).as_posix()
            except ValueError as exc:
                raise ValueError(f"source file resolves outside project root: {path}") from exc
            resource_patches = self.registry.parse_to_patches(
                resource_uri,
                resolved.read_text(encoding="utf-8"),
                protocol_level=protocol_level,
            )
            patches.extend(resource_patches)
            operations_planned += len(resource_patches)

        operations_applied = 0
        storage_patches_applied = 0
        if patches and not dry_run:
            nodes = {
                node.id: node.to_dict()
                for node in self.repository.get_local_nodes()
            }
            edges = {
                (edge.source, edge.target, edge.type): edge.to_dict()
                for edge in self.repository.get_edges()
            }
            for patch in patches:
                if patch.operation == "upsert_node":
                    raw = dict(patch.payload.get("node") or {})
                    if not raw:
                        raw = {
                            "id": patch.target,
                            "type": patch.type,
                            "summary": patch.payload.get("summary", ""),
                            "evidence": patch.evidence,
                            "status": patch.payload.get("status", "draft"),
                            "freshness": patch.payload.get("freshness", now_local_iso(self.repository.config)),
                            "trust": patch.payload.get("trust", "verified" if patch.confidence > 0.8 else "unverified"),
                            "domain": patch.domain,
                            "related_nodes": patch.payload.get("related_nodes", []),
                            "tags": patch.payload.get("tags", []),
                            "confidence": patch.confidence,
                        }
                    nodes[raw["id"]] = {**nodes.get(raw["id"], {}), **raw}
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
                    key = (raw["source"], raw["target"], raw["type"])
                    edges[key] = {**edges.get(key, {}), **raw}

            store = RelationPatchStore(self.repository)
            replacements = [
                RelationPatch(
                    operation="replace_nodes",
                    source="",
                    target="memory/nodes.jsonl",
                    type="file",
                    domain="codebase",
                    confidence=1.0,
                    evidence=[source_root.relative_to(project_root).as_posix()],
                    reason="Bulk codebase source index",
                    created_by_protocol=protocol_level,
                    required_verification_protocol=protocol_level,
                    payload={"nodes": list(nodes.values())},
                ),
                RelationPatch(
                    operation="replace_edges",
                    source="",
                    target="memory/edges.jsonl",
                    type="contains",
                    domain="codebase",
                    confidence=1.0,
                    evidence=[source_root.relative_to(project_root).as_posix()],
                    reason="Bulk codebase source index",
                    created_by_protocol=protocol_level,
                    required_verification_protocol=protocol_level,
                    payload={"edges": list(edges.values())},
                ),
            ]
            replacement_ids = [store.propose(patch) for patch in replacements]
            if not store.apply_many(replacement_ids):
                raise RuntimeError("failed to apply bulk codebase index")
            operations_applied = operations_planned
            storage_patches_applied = len(replacement_ids)

        return {
            "source_root": source_root.relative_to(project_root).as_posix(),
            "files_indexed": len(files),
            "operations_planned": operations_planned,
            "operations_applied": operations_applied,
            "storage_patches_applied": storage_patches_applied,
            "dry_run": dry_run,
        }
