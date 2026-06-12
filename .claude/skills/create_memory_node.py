#!/usr/bin/env python3
"""
Tool: create_memory_node
Description: Create a new memory node in the Memory OS graph.
Usage: python3 create_memory_node.py <node_id> <node_type> <summary> [--tags tag1,tag2]
"""
import sys
import argparse
from memory_os.core.models import MemoryNode
from memory_os.core.config import MemoryOSConfig
from memory_os.core.repository import MemoryRepository
from memory_os.core.storage import FileSystemMemoryStorage

def main():
    parser = argparse.ArgumentParser(description="Create a Memory OS node")
    parser.add_argument("id", help="Unique node ID")
    parser.add_argument("type", help="Type of the node (e.g. rule, fact, concept)")
    parser.add_argument("summary", help="Content/Summary of the node")
    parser.add_argument("--tags", help="Comma-separated tags", default="")
    args = parser.parse_args()
    
    config = MemoryOSConfig()
    repo = MemoryRepository(FileSystemMemoryStorage(), config)
    
    node = MemoryNode(
        id=args.id,
        type=args.type,
        summary=args.summary,
        evidence=[],
        status="verified",
        trust="verified",
        tags=args.tags.split(",") if args.tags else []
    )
    repo.add_node(node)
    
    # Also sync to SQLite immediately
    from memory_os.core.core import MemoryOS
    db = MemoryOS(config)
    db.insert_graph_node(
        node_id=node.id,
        node_type=node.type,
        summary=node.summary,
        status=node.status,
        freshness=node.freshness,
        trust=node.trust,
        tags=",".join(node.tags) if node.tags else None
    )
    
    print(f"Successfully created node: {args.id}")

if __name__ == "__main__":
    main()
