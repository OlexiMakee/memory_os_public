"""
Graph Mapper — structural codebase analysis for Memory OS.

Reads the project snapshot to compute:
  - God nodes: files with the highest in-degree (most depended upon)
  - Module clusters: groups of tightly-coupled files (by directory + import density)
  - Writes agent_context/codebase_map.md for compile-prompt injection
  - Optionally emits module_cluster nodes into memory/nodes.jsonl

Separates extracted facts (AST-derived imports, classes, routes) from inferred
structure (clusters, rankings). Both are useful; only one is ground truth.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple  # noqa: F401

from memory_os.core.config import MemoryOSConfig
from memory_os.core.adapters import CodebaseDomainAdapter, DomainAdapterRegistry
from memory_os.core.storage import FileSystemMemoryStorage

UTC = timezone.utc

GOD_NODE_TOP_N = 8
CLUSTER_TOP_N = 6


def _resolve_dep_to_file(dep: str, all_files: List[str]) -> Optional[str]:
    return CodebaseDomainAdapter().resolve_dependency_to_file(dep, all_files)


def build_dependency_graph(
    items: List[Dict[str, Any]],
) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
    """
    Returns:
        forward: file -> set of files it imports
        reverse: file -> set of files that import it (in-degree sources)
    """
    return CodebaseDomainAdapter().build_dependency_graph(items)


def compute_god_nodes(
    reverse: Dict[str, Set[str]],
    items: List[Dict[str, Any]],
    top_n: int = GOD_NODE_TOP_N,
) -> List[Dict[str, Any]]:
    return CodebaseDomainAdapter().compute_god_nodes(reverse, items, top_n=top_n)


def compute_clusters(
    items: List[Dict[str, Any]],
    forward: Dict[str, Set[str]],
    top_n: int = CLUSTER_TOP_N,
) -> List[Dict[str, Any]]:
    return CodebaseDomainAdapter().compute_clusters(items, forward, top_n=top_n)


def build_markdown(
    god_nodes: List[Dict[str, Any]],
    clusters: List[Dict[str, Any]],
    generated_at: str,
    total_files: int,
) -> str:
    lines = [
        "# Codebase Map",
        f"_Generated: {generated_at} | Files indexed: {total_files}_",
        "",
        "## God Nodes (Load-Bearing Files)",
        "_Ranked by in-degree. Trust: **extracted** (from snapshot AST/imports)._",
        "",
    ]

    if not god_nodes:
        lines.append("_No cross-file dependencies found. Run `memory_os snapshot --write` first._")
    else:
        for i, node in enumerate(god_nodes, 1):
            labels = []
            if node["classes"]:
                labels.append(f"classes: {', '.join(node['classes'][:3])}")
            if node["functions"]:
                labels.append(f"fns: {', '.join(node['functions'][:3])}")
            if node["routes"]:
                labels.append(f"routes: {', '.join(node['routes'][:2])}")
            label_str = f" — {'; '.join(labels)}" if labels else ""
            lines.append(
                f"{i}. **`{node['file']}`** "
                f"(imported by {node['in_degree']} files, layer: {node['layer']})"
                f"{label_str}"
            )
            if node["dependents"]:
                preview = ", ".join(f"`{d}`" for d in node["dependents"][:4])
                if len(node["dependents"]) > 4:
                    preview += f" +{len(node['dependents']) - 4} more"
                lines.append(f"   ↳ depended on by: {preview}")

    lines += [
        "",
        "## Module Clusters",
        "_Grouped by top-level directory, ranked by internal import edges. Trust: **inferred**._",
        "",
    ]

    if not clusters:
        lines.append("_No multi-file clusters detected._")
    else:
        for cluster in clusters:
            lines.append(
                f"### `{cluster['name']}/`  "
                f"({cluster['file_count']} files, {cluster['internal_edges']} internal edges)"
            )
            for f in cluster["files"]:
                lines.append(f"  - `{f}`")
            lines.append("")

    lines += [
        "---",
        "_Run `memory_os graph-map` to refresh. "
        "Run `memory_os search <file>` to see blast radius for a specific file._",
    ]
    return "\n".join(lines)


class GraphMapper:
    def __init__(
        self,
        config: Optional[MemoryOSConfig] = None,
        domain_adapters: Optional[DomainAdapterRegistry] = None,
    ):
        self.config = config or MemoryOSConfig()
        self.storage = FileSystemMemoryStorage()
        self.domain_adapters = domain_adapters or DomainAdapterRegistry()
        self.codebase_adapter = self.domain_adapters.require("codebase")
        if not isinstance(self.codebase_adapter, CodebaseDomainAdapter):
            raise TypeError("codebase domain adapter must be a CodebaseDomainAdapter")

    def run(self, emit_nodes: bool = False) -> Dict[str, Any]:
        snapshot_path = self.config.snapshot_file
        if not snapshot_path.exists():
            return {
                "status": "error",
                "reason": (
                    f"Snapshot not found at {snapshot_path}. "
                    "Run `memory_os snapshot --write` first."
                ),
            }

        snapshot = self.storage.load_json(snapshot_path)
        items = snapshot.get("items", [])
        generated_at = snapshot.get("generated_at", datetime.now(UTC).isoformat().replace("+00:00", "Z"))

        if not items:
            return {"status": "error", "reason": "Snapshot has no items."}

        forward, reverse = self.codebase_adapter.build_dependency_graph(items)
        god_nodes = self.codebase_adapter.compute_god_nodes(reverse, items)
        clusters = self.codebase_adapter.compute_clusters(items, forward)

        md = build_markdown(god_nodes, clusters, generated_at, len(items))
        out_path = self.config.root_dir / "agent_context" / "codebase_map.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")

        if emit_nodes:
            self._emit_cluster_nodes(clusters, generated_at)

        return {
            "status": "success",
            "god_nodes": god_nodes,
            "clusters": clusters,
            "output": str(out_path),
            "total_files": len(items),
        }

    def _emit_cluster_nodes(self, clusters: List[Dict[str, Any]], generated_at: str) -> None:
        """Emit module_cluster MemoryNodes and contains edges.

        Each cluster → MemoryNode with type=module_cluster.
        Each cluster → contains → any existing MemoryNode whose evidence lists files
        in that cluster (connecting structural codebase knowledge to memory facts).
        New nodes trigger a background Stage-0 link inference to wire them into the graph.
        """
        nodes_path = self.config.memory_dir / "nodes.jsonl"
        existing = self.storage.load_jsonl(nodes_path) if nodes_path.exists() else []
        existing_ids = {n["id"] for n in existing}

        new_nodes = []
        emitted_cluster_ids: set = set()
        for cluster in clusters:
            node_id = self.codebase_adapter.cluster_node_id(str(cluster["name"]))
            if node_id in existing_ids:
                continue
            new_nodes.append(self.codebase_adapter.cluster_to_node(cluster, generated_at))
            emitted_cluster_ids.add(node_id)

        if new_nodes:
            from memory_os.core.repository import MemoryRepository
            repo = MemoryRepository(self.storage, self.config)
            for node in new_nodes:
                repo.upsert_node(node)

        # Emit contains edges: cluster -> existing MemoryNodes whose evidence overlaps
        # cluster files.
        edges_path = self.config.memory_dir / "edges.jsonl"
        existing_edges = self.storage.load_jsonl(edges_path) if edges_path.exists() else []
        existing_edge_pairs: Set[Tuple[str, str]] = {
            (e["source"], e["target"]) for e in existing_edges
        }
        all_nodes = existing + new_nodes
        new_edges = self.codebase_adapter.cluster_contains_edges(
            clusters,
            all_nodes,
            emitted_cluster_ids,
            existing_edge_pairs,
        )

        if new_edges:
            from memory_os.core.repository import MemoryRepository
            repo = MemoryRepository(self.storage, self.config)
            for edge in new_edges:
                repo.upsert_edge(edge)

        # Background: re-wire new cluster nodes into the graph via Stage-0 inference.
        if new_nodes:
            import threading as _t
            from memory_os.core.config import MemoryOSConfig as _Cfg
            try:
                from memory_os.agent_brain.executors import _background_link_infer
                _t.Thread(target=_background_link_infer, args=(self.config,), daemon=True).start()
            except Exception as _e:
                import sys as _sys
                print(f'Ignored exception: {_e}', file=_sys.stderr)
