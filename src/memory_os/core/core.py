import sqlite3
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from memory_os.core.interfaces import IMemoryOSConfig

class MemoryOS:
    """Core orchestrator for Memory OS. Handles DB initialization and connection management."""

    def __init__(self, config: Optional[IMemoryOSConfig] = None, db_path: Optional[str] = None):
        if config is None:
            # We delay import to avoid circular dependencies
            from memory_os.core.config import MemoryOSConfig
            config = MemoryOSConfig()
            
        if db_path is None:
            self.db_path = config.db_path
        else:
            self.db_path = Path(db_path)
            
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        """Get a thread-safe connection to the isolated telemetry database."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_db(self):
        """Initialize telemetry and memories tables if they do not exist."""
        conn = self.get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_os_telemetry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prompt_name TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    prompt_hash TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    cached_tokens INTEGER DEFAULT 0,
                    latency_ms INTEGER DEFAULT 0,
                    cost REAL DEFAULT 0.0,
                    status TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_name_ver ON memory_os_telemetry(prompt_name, prompt_version)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_created ON memory_os_telemetry(created_at)")
            
            # Isolated memories table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    summary TEXT,
                    importance REAL DEFAULT 0.0,
                    timestamp INTEGER NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance DESC)")
            
            # FTS5 Virtual Table for full-text search
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                    id UNINDEXED,
                    content,
                    summary,
                    content="memories",
                    content_rowid="rowid"
                )
            """)
            
            # Create triggers to keep FTS index synced
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                    INSERT INTO memories_fts(rowid, id, content, summary)
                    VALUES (new.rowid, new.id, new.content, new.summary);
                END;
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, id, content, summary)
                    VALUES('delete', old.rowid, old.id, old.content, old.summary);
                END;
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, id, content, summary)
                    VALUES('delete', old.rowid, old.id, old.content, old.summary);
                    INSERT INTO memories_fts(rowid, id, content, summary)
                    VALUES (new.rowid, new.id, new.content, new.summary);
                END;
            """)
            
            # Graph Nodes table for Memory OS Phase 5
            conn.execute("""
                CREATE TABLE IF NOT EXISTS graph_nodes (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    status TEXT,
                    freshness TEXT,
                    trust TEXT,
                    tags TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_graph_nodes_type ON graph_nodes(type)")
            
            # FTS5 Virtual Table for graph_nodes
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS graph_nodes_fts USING fts5(
                    id UNINDEXED,
                    type,
                    summary,
                    content="graph_nodes",
                    content_rowid="rowid"
                )
            """)
            
            # Create triggers for graph_nodes_fts
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS graph_nodes_ai AFTER INSERT ON graph_nodes BEGIN
                    INSERT INTO graph_nodes_fts(rowid, id, type, summary)
                    VALUES (new.rowid, new.id, new.type, new.summary);
                END;
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS graph_nodes_ad AFTER DELETE ON graph_nodes BEGIN
                    INSERT INTO graph_nodes_fts(graph_nodes_fts, rowid, id, type, summary)
                    VALUES('delete', old.rowid, old.id, old.type, old.summary);
                END;
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS graph_nodes_au AFTER UPDATE ON graph_nodes BEGIN
                    INSERT INTO graph_nodes_fts(graph_nodes_fts, rowid, id, type, summary)
                    VALUES('delete', old.rowid, old.id, old.type, old.summary);
                    INSERT INTO graph_nodes_fts(rowid, id, type, summary)
                    VALUES (new.rowid, new.id, new.type, new.summary);
                END;
            """)
            
            # Algorithm Performance table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_os_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    algorithm_name TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    metadata TEXT,
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_performance_name ON memory_os_performance(algorithm_name)")
            
            conn.commit()
        finally:
            conn.close()

    def add_or_update_memory(self, memory_id: str, mem_type: str, content: str, 
                             summary: Optional[str] = None, importance: float = 0.0, 
                             timestamp: Optional[int] = None) -> None:
        """Add a memory or update it if it exists by id."""
        if timestamp is None:
            timestamp = int(time.time())
        conn = self.get_connection()
        try:
            conn.execute("""
                INSERT INTO memories (id, type, content, summary, importance, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    type = excluded.type,
                    content = excluded.content,
                    summary = excluded.summary,
                    importance = excluded.importance,
                    timestamp = excluded.timestamp
            """, (memory_id, mem_type, content, summary, importance, timestamp))
            conn.commit()
        finally:
            conn.close()

    def get_memories(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve memories sorted by importance and timestamp descending."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, type, content, summary, importance, timestamp FROM memories ORDER BY importance DESC, timestamp DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def search_memories(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Full-text search across memories using FTS5."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            # rank is the BM25 score provided by FTS5, lower is better. We sort by rank (relevance) and then importance.
            cursor.execute("""
                SELECT m.id, m.type, m.content, m.summary, m.importance, m.timestamp
                FROM memories_fts fts
                JOIN memories m ON m.rowid = fts.rowid
                WHERE memories_fts MATCH ?
                ORDER BY fts.rank, m.importance DESC
                LIMIT ?
            """, (query, limit))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
