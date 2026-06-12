#!/usr/bin/env python3
"""
Tool: archive_memory_node
Description: Mark a memory node as archived (superseded).
Usage: python3 archive_memory_node.py <node_id>
"""
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
