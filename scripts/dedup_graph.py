#!/usr/bin/env python3
"""Deduplicate Memory OS graph nodes and edges."""

import argparse
import json
from pathlib import Path
from collections import OrderedDict

def deduplicate_nodes(nodes_path: Path) -> int:
    if not nodes_path.is_file():
        return 0
    
    nodes_by_id = OrderedDict()
    with nodes_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            node = json.loads(line)
            nid = node["id"]
            if nid not in nodes_by_id:
                nodes_by_id[nid] = node
            else:
                existing = nodes_by_id[nid]
                # Merge lists: evidence, tags, related_nodes
                for list_field in ["evidence", "tags", "related_nodes"]:
                    if list_field in node and isinstance(node[list_field], list):
                        existing_list = existing.get(list_field, [])
                        new_items = [item for item in node[list_field] if item not in existing_list]
                        existing[list_field] = existing_list + new_items
                
                # For scalar fields, newer overwrites older
                for k, v in node.items():
                    if k not in ["evidence", "tags", "related_nodes"]:
                        existing[k] = v

    with nodes_path.open("w", encoding="utf-8") as f:
        for node in nodes_by_id.values():
            f.write(json.dumps(node, ensure_ascii=False) + "\n")
            
    return len(nodes_by_id)

def deduplicate_edges(edges_path: Path) -> int:
    if not edges_path.is_file():
        return 0
        
    edges_by_key = OrderedDict()
    with edges_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            edge = json.loads(line)
            key = (edge.get("source"), edge.get("target"), edge.get("type"))
            if key not in edges_by_key:
                edges_by_key[key] = edge
            else:
                existing = edges_by_key[key]
                # Merge evidence if exists
                if "evidence" in edge and isinstance(edge["evidence"], list):
                    existing_list = existing.get("evidence", [])
                    new_items = [item for item in edge["evidence"] if item not in existing_list]
                    existing["evidence"] = existing_list + new_items
                
                for k, v in edge.items():
                    if k not in ["evidence"]:
                        existing[k] = v

    with edges_path.open("w", encoding="utf-8") as f:
        for edge in edges_by_key.values():
            f.write(json.dumps(edge, ensure_ascii=False) + "\n")

    return len(edges_by_key)

def main():
    parser = argparse.ArgumentParser(description="Deduplicate graph JSONL files.")
    parser.add_argument("--nodes", type=Path, default=Path("memory/nodes.jsonl"))
    parser.add_argument("--edges", type=Path, default=Path("memory/edges.jsonl"))
    args = parser.parse_args()
    
    unique_nodes = deduplicate_nodes(args.nodes)
    unique_edges = deduplicate_edges(args.edges)
    
    print(f"Deduplicated nodes: {unique_nodes} remaining")
    print(f"Deduplicated edges: {unique_edges} remaining")

if __name__ == "__main__":
    main()
