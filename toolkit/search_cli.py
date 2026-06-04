#!/usr/bin/env python3
import sys
import os
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any

ROOT = Path(__file__).resolve().parents[2]
MEMORY_DIR = ROOT / "memory"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory_os import MemoryOSConfig, MemorySearcher

def search_memory(query: str, depth: int = 1) -> List[Dict[str, Any]]:
    config = MemoryOSConfig()
    config.root_dir = ROOT
    config.data["memory_dir"] = str(MEMORY_DIR)
    config.data["snapshot_file"] = str(ROOT / "agent_context" / "memory_snapshot.json")
    searcher = MemorySearcher(config)
    return searcher.search_memory(query, depth)

def main() -> int:
    parser = argparse.ArgumentParser(description="Query Memory OS nodes, codebase symbols, and traverse relations.")
    parser.add_argument("--query", required=True, help="Keyword query or exact symbol.")
    parser.add_argument("--depth", type=int, default=1, help="Graph traversal recursion depth.")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of human-readable text.")
    parser.add_argument("--config", help="Path to memory_os.config.json")
    args = parser.parse_args()

    config_path = args.config or os.environ.get("MEMORY_OS_CONFIG_PATH")
    config = MemoryOSConfig(config_path)
    searcher = MemorySearcher(config)

    matches = searcher.search_memory(args.query, args.depth)

    if args.json:
        print(json.dumps(matches, indent=2))
    else:
        nodes = [m for m in matches if m["type"] != "code_file"]
        code_files = [m for m in matches if m["type"] == "code_file"]

        if not nodes and not code_files:
            print(f"No matches found for query '{args.query}'")
            return 0

        if nodes:
            print(f"Found {len(nodes)} matched memory nodes:")
            for node in nodes:
                print(f"\n[{node['id']}] ({node['type']})")
                print(f"  Summary: {node['summary']}")
                print(f"  Status: {node['status']} | Trust: {node['trust']}")
                if node.get("evidence"):
                    print(f"  Evidence: {', '.join(node['evidence'])}")

        if code_files:
            if nodes:
                print("\n" + "="*50 + "\n")
            print(f"Found {len(code_files)} matched codebase files:")
            for item in code_files:
                print(f"\n[{item['id']}] ({item['layer']}) - Rank {item['rank']} ({item['match_type']})")
                if item.get("classes"):
                    print(f"  Classes: {', '.join(item['classes'])}")
                if item.get("functions"):
                    print(f"  Functions: {', '.join(item['functions'])}")
                if item.get("routes"):
                    print(f"  Routes: {', '.join(item['routes'])}")
                if item.get("dependencies"):
                    print(f"  Dependencies: {', '.join(item['dependencies'])}")
                if item.get("headings"):
                    print(f"  Headings: {', '.join(item['headings'])}")
                preview = item["summary"][:240]
                print(f"  Preview: {preview}...")

    return 0

if __name__ == "__main__":
    sys.exit(main())
