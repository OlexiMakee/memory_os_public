"""
Graph Mapper — Graphify-inspired structural analysis for Memory OS.

Reads the project snapshot to compute:
  - God nodes: files with the highest in-degree (most depended upon)
  - Module clusters: groups of tightly-coupled files (by directory + import density)
  - Writes agent_context/codebase_map.md for compile-prompt injection
  - Optionally emits module_cluster nodes into memory/nodes.jsonl

Graphify's key insight applied here: separate *extracted* facts (AST-derived
imports, classes, routes) from *inferred* structure (clusters, rankings).
Both are useful; only one is ground truth.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from memory_os.core.config import MemoryOSConfig
from memory_os.core.storage import FileSystemMemoryStorage

GOD_NODE_TOP_N = 8
CLUSTER_TOP_N = 6


def _resolve_dep_to_file(dep: str, all_files: List[str]) -> Optional[str]:
    dep_lower = dep.lower()
    for f in all_files:
        p = Path(f)
        stem = p.stem.lower()
        mod_path = p.with_suffix("").as_posix().replace("/", ".").lower()
        if dep_lower == stem or dep_lower == mod_path or mod_path.endswith("." + dep_lower):
            return f
    return None


def build_dependency_graph(
    items: List[Dict[str, Any]],
) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
    """
    Returns:
        forward: file -> set of files it imports
        reverse: file -> set of files that import it (in-degree sources)
    """
    all_files = [item["meta"]["file"] for item in items]
    forward: Dict[str, Set[str]] = defaultdict(set)
    reverse: Dict[str, Set[str]] = defaultdict(set)

    for item in items:
        src = item["meta"]["file"]
        for dep in item["meta"].get("dependencies", []):
            target = _resolve_dep_to_file(dep, all_files)
            if target and target != src:
                forward[src].add(target)
                reverse[target].add(src)

    return dict(forward), dict(reverse)


def compute_god_nodes(
    reverse: Dict[str, Set[str]],
    items: List[Dict[str, Any]],
    top_n: int = GOD_NODE_TOP_N,
) -> List[Dict[str, Any]]:
    """Return top_n files by in-degree. Trust: extracted."""
    in_degree = {
        item["meta"]["file"]: len(reverse.get(item["meta"]["file"], set()))
        for item in items
    }
    ranked = sorted(in_degree.items(), key=lambda x: x[1], reverse=True)
    results = []
    for filepath, degree in ranked[:top_n]:
        if degree == 0:
            break
        item = next((i for i in items if i["meta"]["file"] == filepath), None)
        meta = item["meta"] if item else {}
        results.append({
            "file": filepath,
            "in_degree": degree,
            "layer": meta.get("layer", "unknown"),
            "classes": meta.get("classes", []),
            "functions": meta.get("functions", []),
            "routes": meta.get("routes", []),
            "dependents": sorted(reverse.get(filepath, set())),
            "trust": "extracted",
        })
    return results


def compute_clusters(
    items: List[Dict[str, Any]],
    forward: Dict[str, Set[str]],
    top_n: int = CLUSTER_TOP_N,
) -> List[Dict[str, Any]]:
    """
    Group files by top-level directory; rank by internal coupling.
    Trust: inferred (directory grouping is structural, not semantic).
    """
    dir_files: Dict[str, List[str]] = defaultdict(list)
    for item in items:
        f = item["meta"]["file"]
        top_dir = Path(f).parts[0] if len(Path(f).parts) > 1 else "root"
        dir_files[top_dir].append(f)

    clusters = []
    for dir_name, files in sorted(dir_files.items(), key=lambda x: -len(x[1])):
        if len(files) < 2:
            continue
        file_set = set(files)
        internal_edges = sum(len(forward.get(f, set()) & file_set) for f in files)
        clusters.append({
            "name": dir_name,
            "files": sorted(files),
            "file_count": len(files),
            "internal_edges": internal_edges,
            "trust": "inferred",
        })
    return sorted(clusters, key=lambda x: x["internal_edges"], reverse=True)[:top_n]


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
    def __init__(self, config: Optional[MemoryOSConfig] = None):
        self.config = config or MemoryOSConfig()
        self.storage = FileSystemMemoryStorage()

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
        generated_at = snapshot.get("generated_at", datetime.utcnow().isoformat() + "Z")

        if not items:
            return {"status": "error", "reason": "Snapshot has no items."}

        forward, reverse = build_dependency_graph(items)
        god_nodes = compute_god_nodes(reverse, items)
        clusters = compute_clusters(items, forward)

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
        nodes_path = self.config.memory_dir / "nodes.jsonl"
        existing = self.storage.load_jsonl(nodes_path) if nodes_path.exists() else []
        existing_ids = {n["id"] for n in existing}

        new_nodes = []
        for cluster in clusters:
            node_id = f"structure.cluster.{cluster['name'].replace('/', '.')}"
            if node_id in existing_ids:
                continue
            new_nodes.append({
                "id": node_id,
                "type": "module_cluster",
                "summary": (
                    f"Module cluster '{cluster['name']}': "
                    f"{cluster['file_count']} files, "
                    f"{cluster['internal_edges']} internal import edges. "
                    f"Files: {', '.join(cluster['files'][:6])}"
                    + (" …" if len(cluster["files"]) > 6 else ".")
                ),
                "evidence": cluster["files"],
                "status": "verified",
                "freshness": generated_at,
                "trust": "inferred",
                "related_nodes": [],
            })

        if new_nodes:
            with open(nodes_path, "a", encoding="utf-8") as f:
                for node in new_nodes:
                    f.write(json.dumps(node, ensure_ascii=False, separators=(",", ":")) + "\n")
