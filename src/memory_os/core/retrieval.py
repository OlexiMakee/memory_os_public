from typing import List, Dict, Any, Optional
from memory_os.core.core import MemoryOS
from memory_os.core.interfaces import IMemoryOSConfig

class LayeredRetrieval:
    """Multi-layered, graph-aware SQLite retrieval for Memory OS."""
    
    def __init__(self, config: IMemoryOSConfig):
        self.db = MemoryOS(config)

    def search_nodes(self, query: str, limit: int = 10, type: Optional[str] = None) -> List[Dict[str, Any]]:
        """FTS5 search across graph nodes."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            if type:
                cursor.execute("""
                    SELECT n.id, n.type, n.summary, n.status, n.trust, n.tags
                    FROM graph_nodes_fts fts
                    JOIN graph_nodes n ON n.rowid = fts.rowid
                    WHERE graph_nodes_fts MATCH ? AND n.type = ?
                    ORDER BY fts.rank
                    LIMIT ?
                """, (query, type, limit))
            else:
                cursor.execute("""
                    SELECT n.id, n.type, n.summary, n.status, n.trust, n.tags
                    FROM graph_nodes_fts fts
                    JOIN graph_nodes n ON n.rowid = fts.rowid
                    WHERE graph_nodes_fts MATCH ?
                    ORDER BY fts.rank
                    LIMIT ?
                """, (query, limit))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_node_context(self, node_id: str, depth: int = 1) -> Dict[str, Any]:
        """Hierarchical node summarization query: fetches node and its surrounding edges up to a certain depth."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM graph_nodes WHERE id = ?", (node_id,))
            node_row = cursor.fetchone()
            if not node_row:
                return {}
            
            node = dict(node_row)
            
            # Fetch direct inbound and outbound edges
            cursor.execute("SELECT source, type FROM graph_edges WHERE target = ?", (node_id,))
            inbound = [dict(row) for row in cursor.fetchall()]
            
            cursor.execute("SELECT target, type FROM graph_edges WHERE source = ?", (node_id,))
            outbound = [dict(row) for row in cursor.fetchall()]
            
            return {
                "node": node,
                "inbound_edges": inbound,
                "outbound_edges": outbound,
                "depth": depth
            }
        finally:
            conn.close()
