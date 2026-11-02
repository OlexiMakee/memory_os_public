#!/usr/bin/env python3
"""Legacy compatibility extractor for the local Memory OS graph.

The script acts as the main entrypoint for extracting local Memory OS graphs.
It operates on Memory OS files and defaults to a read-only summary.
Writes require --write and stay inside the configured project root.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from memory_os.core.config import MemoryOSConfig
from memory_os.core.file_policy import (
    classify_private_path,
    load_export_ignore_patterns,
    normalize_rel_path,
)
from memory_os.core.safe_id import confine_to_root, validate_safe_node_id
from memory_os.core.write_budget import ArtifactWriteBudget


JsonRow = Dict[str, Any]


def _load_jsonl(path: Path, *, strict: bool) -> Tuple[List[JsonRow], List[str]]:
    rows: List[JsonRow] = []
    errors: List[str] = []
    if not path.is_file():
        return rows, [f"{path}: file not found"]

    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                msg = f"{path}:{line_no}: invalid JSON: {exc}"
                if strict:
                    raise ValueError(msg) from exc
                errors.append(msg)
                continue
            if not isinstance(value, dict):
                msg = f"{path}:{line_no}: JSONL row is not an object"
                if strict:
                    raise ValueError(msg)
                errors.append(msg)
                continue
            rows.append(value)
    return rows, errors


def _line_count(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        return sum(1 for line in handle if line.strip())


def _candidate_sources(config: MemoryOSConfig) -> List[Tuple[str, Path, Path]]:
    return [
        ("workspace", config.memory_dir / "nodes.jsonl", config.memory_dir / "edges.jsonl"),
        ("package", config.internal_memory_dir / "nodes.jsonl", config.internal_memory_dir / "edges.jsonl"),
    ]


def _resolve_graph_paths(args: argparse.Namespace, config: MemoryOSConfig) -> Tuple[str, Path, Path]:
    if args.source == "custom":
        if not args.nodes or not args.edges:
            raise ValueError("--source custom requires --nodes and --edges")
        return (
            "custom",
            confine_to_root(args.nodes, config.root_dir),
            confine_to_root(args.edges, config.root_dir),
        )

    for kind, nodes_path, edges_path in _candidate_sources(config):
        if args.source != "auto" and args.source != kind:
            continue
        if nodes_path.is_file() and edges_path.is_file():
            if _line_count(nodes_path) > 0 or _line_count(edges_path) > 0:
                return kind, nodes_path, edges_path

    if args.source != "auto":
        for kind, nodes_path, edges_path in _candidate_sources(config):
            if kind == args.source:
                return kind, nodes_path, edges_path

    candidates = ", ".join(
        f"{kind}: {nodes.relative_to(config.root_dir) if _is_under(nodes, config.root_dir) else nodes}"
        for kind, nodes, _edges in _candidate_sources(config)
    )
    raise FileNotFoundError(f"no non-empty Memory OS graph found ({candidates})")


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _safe_rel(path: Path, root: Path) -> str:
    try:
        return normalize_rel_path(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _private_evidence_hits(
    node: JsonRow,
    *,
    export_ignore_patterns: Sequence[str],
) -> List[str]:
    hits: List[str] = []
    evidence = node.get("evidence", [])
    if not isinstance(evidence, list):
        return hits

    for item in evidence:
        if not isinstance(item, str):
            continue
        reason = classify_private_path(item, export_ignore_patterns=export_ignore_patterns)
        if reason:
            hits.append(f"{item}:{reason}")
    return hits


def _filter_nodes(
    nodes: Sequence[JsonRow],
    *,
    include_private: bool,
    export_ignore_patterns: Sequence[str],
) -> Tuple[List[JsonRow], Dict[str, Any]]:
    kept: List[JsonRow] = []
    invalid_ids: List[str] = []
    private_nodes: List[str] = []
    seen: Counter[str] = Counter()

    for node in nodes:
        node_id = node.get("id")
        try:
            validate_safe_node_id(node_id)
        except (TypeError, ValueError):
            invalid_ids.append(str(node_id))
            continue

        private_hits = _private_evidence_hits(node, export_ignore_patterns=export_ignore_patterns)
        if private_hits and not include_private:
            private_nodes.append(f"{node_id} ({', '.join(private_hits[:3])})")
            continue

        seen[str(node_id)] += 1
        kept.append(dict(node))

    duplicate_ids = sorted(node_id for node_id, count in seen.items() if count > 1)
    return kept, {
        "invalid_node_ids": invalid_ids,
        "private_nodes": private_nodes,
        "duplicate_node_id_count": len(duplicate_ids),
        "duplicate_node_ids_sample": duplicate_ids[:25],
    }


def _filter_edges(edges: Sequence[JsonRow], kept_node_ids: Iterable[str]) -> Tuple[List[JsonRow], Dict[str, Any]]:
    kept_ids = set(kept_node_ids)
    kept_edges: List[JsonRow] = []
    invalid_edges: List[str] = []
    dangling_edges = 0

    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        try:
            validate_safe_node_id(source, "edge source")
            validate_safe_node_id(target, "edge target")
        except (TypeError, ValueError):
            invalid_edges.append(f"{source!r}->{target!r}")
            continue
        if source not in kept_ids or target not in kept_ids:
            dangling_edges += 1
            continue
        kept_edges.append(dict(edge))

    return kept_edges, {
        "invalid_edges": invalid_edges,
        "dangling_edges": dangling_edges,
    }


def _counter(values: Iterable[Any]) -> Dict[str, int]:
    counter: Counter[str] = Counter(str(v) for v in values if v not in (None, ""))
    return dict(counter.most_common())


def _top_tags(nodes: Sequence[JsonRow], limit: int = 20) -> Dict[str, int]:
    counter: Counter[str] = Counter()
    for node in nodes:
        tags = node.get("tags", [])
        if isinstance(tags, list):
            counter.update(str(tag) for tag in tags if tag)
    return dict(counter.most_common(limit))


def build_extract(args: argparse.Namespace, config: MemoryOSConfig) -> Tuple[Dict[str, Any], List[JsonRow], List[JsonRow]]:
    source_kind, nodes_path, edges_path = _resolve_graph_paths(args, config)
    nodes, node_errors = _load_jsonl(nodes_path, strict=args.strict)
    edges, edge_errors = _load_jsonl(edges_path, strict=args.strict)

    export_ignore_patterns = load_export_ignore_patterns(config.root_dir)
    kept_nodes, node_filter_report = _filter_nodes(
        nodes,
        include_private=args.include_private,
        export_ignore_patterns=export_ignore_patterns,
    )
    kept_node_ids = [str(node["id"]) for node in kept_nodes]
    kept_edges, edge_filter_report = _filter_edges(edges, kept_node_ids)

    summary = {
        "entrypoint": "scripts/memory_extract.py",
        "project": "memory_os",
        "mode": "write" if args.write else "dry-run",
        "source": {
            "kind": source_kind,
            "nodes": _safe_rel(nodes_path, config.root_dir),
            "edges": _safe_rel(edges_path, config.root_dir),
        },
        "counts": {
            "raw_nodes": len(nodes),
            "raw_edges": len(edges),
            "exportable_nodes": len(kept_nodes),
            "exportable_edges": len(kept_edges),
        },
        "node_types": _counter(node.get("type") for node in kept_nodes),
        "node_statuses": _counter(node.get("status") for node in kept_nodes),
        "node_trust": _counter(node.get("trust") for node in kept_nodes),
        "edge_types": _counter(edge.get("type") for edge in kept_edges),
        "top_tags": _top_tags(kept_nodes),
        "filters": {
            **node_filter_report,
            **edge_filter_report,
            "jsonl_errors": node_errors + edge_errors,
            "include_private": args.include_private,
        },
    }
    return summary, kept_nodes, kept_edges


def _summary_text(summary: Dict[str, Any]) -> str:
    counts = summary["counts"]
    source = summary["source"]
    filters = summary["filters"]
    lines = [
        "Memory OS graph extract",
        f"mode: {summary['mode']}",
        f"source: {source['kind']} ({source['nodes']}, {source['edges']})",
        f"nodes: {counts['exportable_nodes']} exportable / {counts['raw_nodes']} raw",
        f"edges: {counts['exportable_edges']} exportable / {counts['raw_edges']} raw",
        f"invalid node ids: {len(filters['invalid_node_ids'])}",
        f"private nodes skipped: {len(filters['private_nodes'])}",
        f"duplicate node ids: {filters['duplicate_node_id_count']}",
        f"dangling edges skipped: {filters['dangling_edges']}",
        f"jsonl errors: {len(filters['jsonl_errors'])}",
    ]
    if summary["node_types"]:
        lines.append("node types: " + ", ".join(f"{k}={v}" for k, v in summary["node_types"].items()))
    return "\n".join(lines)


def _summary_markdown(summary: Dict[str, Any]) -> str:
    counts = summary["counts"]
    source = summary["source"]
    filters = summary["filters"]
    lines = [
        "# Memory OS Graph Extract",
        "",
        f"- Entrypoint: `{summary['entrypoint']}`",
        f"- Mode: `{summary['mode']}`",
        f"- Source: `{source['kind']}`",
        f"- Nodes file: `{source['nodes']}`",
        f"- Edges file: `{source['edges']}`",
        f"- Nodes: `{counts['exportable_nodes']}` exportable / `{counts['raw_nodes']}` raw",
        f"- Edges: `{counts['exportable_edges']}` exportable / `{counts['raw_edges']}` raw",
        f"- Invalid node ids: `{len(filters['invalid_node_ids'])}`",
        f"- Private nodes skipped: `{len(filters['private_nodes'])}`",
        f"- Duplicate node ids: `{filters['duplicate_node_id_count']}`",
        f"- Dangling edges skipped: `{filters['dangling_edges']}`",
        f"- JSONL errors: `{len(filters['jsonl_errors'])}`",
        "",
        "## Node Types",
        "",
    ]
    if summary["node_types"]:
        lines.extend(f"- `{name}`: {count}" for name, count in summary["node_types"].items())
    else:
        lines.append("- none")
    lines.extend(["", "## Edge Types", ""])
    if summary["edge_types"]:
        lines.extend(f"- `{name}`: {count}" for name, count in summary["edge_types"].items())
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def _jsonl(rows: Sequence[JsonRow]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)


def write_extract(
    args: argparse.Namespace,
    config: MemoryOSConfig,
    summary: Dict[str, Any],
    nodes: Sequence[JsonRow],
    edges: Sequence[JsonRow],
) -> List[Path]:
    output_dir = confine_to_root(args.output_dir, config.root_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    budget = ArtifactWriteBudget(config)

    written: List[Path] = []
    files = {
        "summary.json": json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        "summary.md": _summary_markdown(summary),
    }
    if args.include_graph:
        files["nodes.jsonl"] = _jsonl(nodes)
        files["edges.jsonl"] = _jsonl(edges)

    for name, text in files.items():
        path = output_dir / name
        budget.write_text(path, text, encoding="utf-8")
        written.append(path)
    return written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect or export the local Memory OS graph."
    )
    parser.add_argument("--config", default=None, help="Path to memory_os.config.json.")
    parser.add_argument("--source", choices={"auto", "workspace", "package", "custom"}, default="auto")
    parser.add_argument("--nodes", default=None, help="Custom nodes.jsonl path inside the configured root.")
    parser.add_argument("--edges", default=None, help="Custom edges.jsonl path inside the configured root.")
    parser.add_argument("--format", choices={"text", "json", "markdown"}, default="text")
    parser.add_argument("--write", action="store_true", help="Write summary artifacts under agent_context.")
    parser.add_argument("--include-graph", action="store_true", help="With --write, also write filtered nodes/edges JSONL.")
    parser.add_argument("--include-private", action="store_true", help="Include nodes whose evidence points at private/export-ignore files.")
    parser.add_argument("--output-dir", default="agent_context/memory_extract")
    parser.add_argument("--strict", action="store_true", help="Fail on malformed JSONL rows instead of reporting and skipping them.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = MemoryOSConfig(config_path=args.config)

    try:
        summary, nodes, edges = build_extract(args, config)
    except Exception as exc:
        print(f"memory_extract: {exc}", file=sys.stderr)
        return 2

    if args.write:
        try:
            written = write_extract(args, config, summary, nodes, edges)
        except Exception as exc:
            print(f"memory_extract: write failed: {exc}", file=sys.stderr)
            return 1
        summary["written"] = [_safe_rel(path, config.root_dir) for path in written]

    if args.format == "json":
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    elif args.format == "markdown":
        print(_summary_markdown(summary), end="")
    else:
        print(_summary_text(summary))
        if args.write:
            for rel_path in summary.get("written", []):
                print(f"wrote: {rel_path}")

    filters = summary["filters"]
    if args.strict and filters["jsonl_errors"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
