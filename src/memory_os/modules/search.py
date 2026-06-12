import json
from pathlib import Path
from typing import List, Dict, Set, Any, Optional
from memory_os.core.interfaces import IMemoryOSConfig, IMemoryStorage
from memory_os.core.repository import MemoryRepository
from memory_os.core.config import MemoryOSConfig
from memory_os.core.storage import FileSystemMemoryStorage

class MemorySearcher:
    """Queries Memory OS nodes, codebase symbols, and traverses graph relations."""

    def __init__(
        self,
        config: Optional[IMemoryOSConfig] = None,
        repository: Optional[MemoryRepository] = None
    ):
        self.config = config or MemoryOSConfig()
        storage = FileSystemMemoryStorage()
        self.storage = storage
        self.repository = repository or MemoryRepository(storage, self.config)

    def _load_nodes(self) -> List[Dict[str, Any]]:
        main_nodes = self.storage.load_jsonl(self.config.memory_dir / "nodes.jsonl")
        internal_nodes = self.storage.load_jsonl(self.config.internal_memory_dir / "nodes.jsonl")
        return main_nodes + internal_nodes

    def _load_edges(self) -> List[Dict[str, Any]]:
        main_edges = self.storage.load_jsonl(self.config.memory_dir / "edges.jsonl")
        internal_edges = self.storage.load_jsonl(self.config.internal_memory_dir / "edges.jsonl")
        return main_edges + internal_edges

    def _load_snapshot(self) -> Dict[str, Any]:
        snapshot_file = self.config.snapshot_file
        return self.storage.load_json(snapshot_file)

    def traverse_graph(self, start_node_ids: Set[str], depth: int, 
                       nodes_by_id: Dict[str, Dict[str, Any]], edges: List[Dict[str, Any]]) -> Set[str]:
        visited = set(start_node_ids)
        current_level = set(start_node_ids)

        for _ in range(depth):
            next_level = set()
            for node_id in current_level:
                node = nodes_by_id.get(node_id)
                if node and "related_nodes" in node:
                    for rel in node["related_nodes"]:
                        if rel not in visited:
                            next_level.add(rel)
                            visited.add(rel)

                for edge in edges:
                    if edge["source"] == node_id and edge["target"] not in visited:
                        next_level.add(edge["target"])
                        visited.add(edge["target"])
                    elif edge["target"] == node_id and edge["source"] not in visited:
                        next_level.add(edge["source"])
                        visited.add(edge["source"])

            current_level = next_level
            if not current_level:
                break

        return visited

    def traverse_dependencies(self, start_files: Set[str], depth: int, 
                              items_by_file: Dict[str, Dict[str, Any]]) -> Set[str]:
        visited = set(start_files)
        current_level = set(start_files)

        for _ in range(depth):
            next_level = set()
            for filepath in current_level:
                item = items_by_file.get(filepath)
                if not item:
                    continue
                dependencies = item.get("meta", {}).get("dependencies", [])
                for dep in dependencies:
                    dep_lower = dep.lower()
                    for other_file in items_by_file:
                        other_path = Path(other_file)
                        other_name = other_path.stem.lower()
                        other_mod = other_path.with_suffix("").as_posix().replace("/", ".").lower()
                        if (dep_lower == other_name or 
                            dep_lower in other_file.lower().split("/") or 
                            dep_lower == other_mod or 
                            other_mod.endswith("." + dep_lower)):
                            if other_file not in visited:
                                next_level.add(other_file)
                                visited.add(other_file)
            current_level = next_level
            if not current_level:
                break
        return visited

    def search_memory(self, query: str, depth: int = 1) -> List[Dict[str, Any]]:
        nodes = self._load_nodes()
        edges = self._load_edges()
        snapshot = self._load_snapshot()

        query_lower = query.strip().lower()

        # 1. Search memory nodes using SQLite Graph Index (Phase 5)
        from memory_os.core.core import MemoryOS
        db = MemoryOS(self.config)
        conn = db.get_connection()
        matched_node_ids = set()
        nodes_by_id = {}
        try:
            # Load all active nodes into memory for traversal
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM graph_nodes WHERE valid_to IS NULL")
            for row in cursor.fetchall():
                d = dict(row)
                d["evidence"] = [] # SQLite doesn't store array, we'll just mock it or fetch from JSONL if needed
                nodes_by_id[d["id"]] = d
            
            # Fast search via SQLite FTS5 Match
            # Note: We query the graph_nodes_fts virtual table for efficient full-text indexing
            # Join with graph_nodes to ensure we only return active nodes
            # We use snippet() to extract the exact match context for RAG
            cursor.execute("""
                SELECT f.id, snippet(graph_nodes_fts, -1, '<b>', '</b>', '...', 64) AS match_snippet 
                FROM graph_nodes_fts f
                JOIN graph_nodes n ON f.rowid = n.rowid
                WHERE f.graph_nodes_fts MATCH ? AND n.valid_to IS NULL
            """, (query,))
            
            snippets_by_id = {}
            for row in cursor.fetchall():
                matched_node_ids.add(row["id"])
                snippets_by_id[row["id"]] = row["match_snippet"]
                
        finally:
            conn.close()

        all_matched_node_ids = self.traverse_graph(matched_node_ids, depth, nodes_by_id, edges)
        
        matched_nodes = []
        for nid in all_matched_node_ids:
            if nid in nodes_by_id:
                node_copy = dict(nodes_by_id[nid])
                if nid in snippets_by_id:
                    node_copy["match_snippet"] = snippets_by_id[nid]
                matched_nodes.append(node_copy)

        # 2. Search codebase items
        items = snapshot.get("items", [])
        items_by_file = {item["meta"]["file"]: item for item in items}

        exact_files = set()
        lexical_files = set()

        for item in items:
            meta = item.get("meta", {})
            filepath = meta.get("file", "")
            filepath_lower = filepath.lower()

            if query_lower == filepath_lower or query_lower == Path(filepath).name.lower() or query_lower == Path(filepath).stem.lower():
                exact_files.add(filepath)
                continue

            matched_meta = False
            for key, val_list in meta.items():
                if key in ["file", "layer"]:
                    continue
                if isinstance(val_list, list):
                    for info in val_list:
                        info_str = str(info).split(":")[0].lower()
                        if query_lower == info_str or query_lower in info_str:
                            exact_files.add(filepath)
                            matched_meta = True
                            break
                if matched_meta:
                    break
                    
            if matched_meta:
                continue

            if query_lower in item.get("vector_text", "").lower():
                lexical_files.add(filepath)

        traversed_files = self.traverse_dependencies(exact_files, depth, items_by_file)

        def to_node_shape(fp: str, rank: int, match_type: str) -> Dict[str, Any]:
            item = items_by_file[fp]
            meta = item["meta"]
            return {
                "id": f"file:{fp}",
                "type": "code_file",
                "summary": item.get("vector_text", ""),
                "evidence": [fp],
                "status": "verified",
                "freshness": snapshot.get("generated_at", ""),
                "trust": "verified",
                "related_nodes": [],
                "classes": meta.get("classes", []),
                "functions": meta.get("functions", []),
                "routes": meta.get("routes", []),
                "dependencies": meta.get("dependencies", []),
                "headings": meta.get("headings", []),
                "match_type": match_type,
                "rank": rank,
                "layer": meta.get("layer", "")
            }

        results_code = []

        for f in exact_files:
            results_code.append(to_node_shape(f, 1, "exact_symbol"))

        for f in traversed_files - exact_files:
            results_code.append(to_node_shape(f, 2, "code_dependency"))

        for f in lexical_files - traversed_files - exact_files:
            results_code.append(to_node_shape(f, 3, "lexical"))

        return matched_nodes + results_code
