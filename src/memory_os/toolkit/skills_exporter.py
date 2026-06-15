import os
from pathlib import Path
from memory_os.core.config import MemoryOSConfig

CREATE_NODE_SKILL = """#!/usr/bin/env python3
\"\"\"
Tool: create_memory_node
Description: Create a new memory node in the Memory OS graph.
Usage: python3 create_memory_node.py <node_id> <node_type> <summary> [--tags tag1,tag2]
\"\"\"
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
"""

ARCHIVE_NODE_SKILL = """#!/usr/bin/env python3
\"\"\"
Tool: archive_memory_node
Description: Mark a memory node as archived (superseded).
Usage: python3 archive_memory_node.py <node_id>
\"\"\"
import sys
import argparse
from memory_os.core.config import MemoryOSConfig
from memory_os.core.core import MemoryOS

def main():
    parser = argparse.ArgumentParser(description="Archive a Memory OS node")
    parser.add_argument("id", help="Unique node ID to archive")
    args = parser.parse_args()
    
    config = MemoryOSConfig()
    db = MemoryOS(config)
    conn = db.get_connection()
    try:
        # We supersede it by setting valid_to = CURRENT_TIMESTAMP
        cursor = conn.cursor()
        cursor.execute("UPDATE graph_nodes SET valid_to = datetime('now', 'localtime') WHERE id = ? AND valid_to IS NULL", (args.id,))
        if cursor.rowcount > 0:
            print(f"Successfully archived active node: {args.id}")
        else:
            print(f"No active node found with ID: {args.id}")
        conn.commit()
    finally:
        conn.close()

if __name__ == "__main__":
    main()
"""

def export_claude_skills(root_dir: Path):
    target_dir = root_dir / ".claude" / "skills"
    target_dir.mkdir(parents=True, exist_ok=True)
    
    with open(target_dir / "create_memory_node.py", "w") as f:
        f.write(CREATE_NODE_SKILL)
    
    with open(target_dir / "archive_memory_node.py", "w") as f:
        f.write(ARCHIVE_NODE_SKILL)
    
    # Make them executable (no-op on Windows, which uses file associations)
    import sys as _sys
    if _sys.platform != "win32":
        (target_dir / "create_memory_node.py").chmod(0o755)
        (target_dir / "archive_memory_node.py").chmod(0o755)
    print(f"Exported Memory OS write-skills to {target_dir}")
