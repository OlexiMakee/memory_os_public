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
                    edge_source = edge.get("source")
                    edge_target = edge.get("target")
                    if edge_source is None or edge_target is None:
                        # Malformed edge — skip rather than crash the whole traversal.
                        continue
                    if edge_source == node_id and edge_target not in visited:
                        next_level.add(edge_target)
                        visited.add(edge_target)
                    elif edge_target == node_id and edge_source not in visited:
                        next_level.add(edge_source)
                        visited.add(edge_source)

            current_level = next_level
            if not current_level:
                break

        return visited

    def _build_reverse_dep_map(
        self, items_by_file: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Set[str]]:
        """Build file -> set of files that import it (for blast radius queries)."""
        all_files = list(items_by_file.keys())
        reverse: Dict[str, Set[str]] = {f: set() for f in all_files}
        for src_file, item in items_by_file.items():
            for dep in item.get("meta", {}).get("dependencies", []):
                dep_lower = dep.lower()
                for other_file in all_files:
                    other_path = Path(other_file)
                    other_stem = other_path.stem.lower()
                    other_mod = other_path.with_suffix("").as_posix().replace("/", ".").lower()
                    if (dep_lower == other_stem
                            or dep_lower == other_mod
                            or other_mod.endswith("." + dep_lower)):
                        if other_file != src_file:
                            reverse[other_file].add(src_file)
                            break
        return reverse

    def traverse_dependents(
        self, start_files: Set[str], depth: int,
        reverse_map: Dict[str, Set[str]]
    ) -> Set[str]:
        """Traverse reverse dependency edges — files that would be affected if start_files change."""
        visited = set(start_files)
        current_level = set(start_files)
        for _ in range(depth):
            next_level = set()
            for filepath in current_level:
                for dependent in reverse_map.get(filepath, set()):
                    if dependent not in visited:
                        next_level.add(dependent)
                        visited.add(dependent)
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
                            dep_lower in other_path.as_posix().lower().split("/") or
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

        import re
        def tokenize(text: str) -> set:
            return {w for w in re.split(r'\W+', text.lower()) if len(w) > 2}
        
        query_tokens = tokenize(query)

        # 1. Search memory nodes
        nodes_by_id = {node["id"]: node for node in nodes if node.get("id")}
        matched_node_ids = set()
        node_scores = {}
        
        sqlite_results = []
        if getattr(self.repository, "indexer", None) and hasattr(self.repository.indexer, "search_graph_nodes"):
            # Use Layered Retrieval via SQLite FTS5 (Phase 5)
            # Remove characters that FTS5 considers syntax (e.g. quotes, brackets)
            safe_query = re.sub(r'[^\w\s]', ' ', query).strip()
            if safe_query:
                # FTS5 needs asterisk for prefix matching on the last word for better semantic feel
                fts_query = " ".join([w for w in safe_query.split()])
                if fts_query:
                    # Append * to the last term for prefix matching if it doesn't end with a space
                    if not query.endswith(' '):
                        fts_query += '*'
                    sqlite_results = self.repository.indexer.search_graph_nodes(fts_query, limit=100)
        
        if sqlite_results:
            # We got fast indexed results from SQLite!
            for res in sqlite_results:
                nid = res["id"]
                matched_node_ids.add(nid)
                # Ensure stale/superseded are downranked
                score = res.get("search_score", 1.0)
                if res.get("status") in ["stale", "superseded"]:
                    score *= 0.5
                node_scores[nid] = score
        else:
            # Fallback to pure Python fuzzy array scan
            for node in nodes:
                node_id = node.get("id")
                if not node_id:
                    continue
                
                score = 0.0
                text_fields = [
                    str(node_id),
                    str(node.get("summary", "")),
                    str(node.get("type", "")),
                    " ".join(str(ev) for ev in node.get("evidence", []) or []),
                    " ".join(str(tag) for tag in node.get("tags", []) or [])
                ]
                full_text = " ".join(text_fields).lower()
                
                if query_lower in full_text:
                    score += 10.0
                    
                if query_tokens:
                    node_tokens = tokenize(full_text)
                    overlap = query_tokens.intersection(node_tokens)
                    if len(query_tokens) > 0:
                        score += (len(overlap) / len(query_tokens)) * 5.0
                    
                if score >= 1.5:
                    if node.get("status") in ["stale", "superseded"]:
                        score *= 0.5
                    matched_node_ids.add(node_id)
                    node_scores[node_id] = score

        all_matched_node_ids = self.traverse_graph(matched_node_ids, depth, nodes_by_id, edges)
        matched_nodes = []
        for nid in all_matched_node_ids:
            if nid in nodes_by_id:
                n = nodes_by_id[nid]
                n["search_score"] = node_scores.get(nid, 0.5)
                matched_nodes.append(n)
        
        # Sort matched nodes by score descending
        matched_nodes.sort(key=lambda x: x.get("search_score", 0.0), reverse=True)

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

        # Blast radius: files that import the queried files (affected if query target changes)
        blast_files: Set[str] = set()
        if exact_files:
            reverse_map = self._build_reverse_dep_map(items_by_file)
            blast_files = self.traverse_dependents(exact_files, depth, reverse_map) - exact_files

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

        # Blast radius results — files that would break if queried file changes
        for f in blast_files - traversed_files - exact_files:
            results_code.append(to_node_shape(f, 4, "blast_radius"))

        for f in lexical_files - traversed_files - exact_files - blast_files:
            results_code.append(to_node_shape(f, 3, "lexical"))

        return matched_nodes + results_code
