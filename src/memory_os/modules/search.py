import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Set, Any, Optional
from memory_os.core.adapters import CodebaseDomainAdapter, DomainAdapterRegistry
from memory_os.core.interfaces import IMemoryOSConfig, IMemoryStorage
from memory_os.core.node_stats import NodeStatsStore
from memory_os.core.repository import MemoryRepository
from memory_os.core.config import MemoryOSConfig
from memory_os.core.storage import FileSystemMemoryStorage

VERBATIM_QUERY_SCORE = 10.0

class MemorySearcher:
    """Queries Memory OS nodes, codebase symbols, and traverses graph relations."""

    def __init__(
        self,
        config: Optional[IMemoryOSConfig] = None,
        repository: Optional[MemoryRepository] = None,
        domain_adapters: Optional[DomainAdapterRegistry] = None,
    ):
        self.config = config or MemoryOSConfig()
        storage = FileSystemMemoryStorage()
        self.storage = storage
        if repository is None:
            from memory_os.core.core import MemoryOS
            repository = MemoryRepository(storage, self.config, indexer=MemoryOS(self.config))
        self.repository = repository
        self._query_cache = {}
        self._cache_version = ""
        self.domain_adapters = domain_adapters or DomainAdapterRegistry()
        self.codebase_adapter = self.domain_adapters.require("codebase")
        if not isinstance(self.codebase_adapter, CodebaseDomainAdapter):
            raise TypeError("codebase domain adapter must be a CodebaseDomainAdapter")

    def _load_nodes(self) -> List[Dict[str, Any]]:
        roots = getattr(self.config, "memory_roots", [self.config.root_dir])
        seen_ids: Set[str] = set()
        all_nodes: List[Dict[str, Any]] = []

        for idx, root in enumerate(roots):
            scope = "local" if idx == 0 else ("global" if root == Path.home() / ".memory_os" else "project")
            nodes_path = root / "memory" / "nodes.jsonl"
            if nodes_path.exists():
                nodes = self.storage.load_jsonl(nodes_path)
                for n in nodes:
                    nid = n.get("id")
                    if nid and nid not in seen_ids:
                        seen_ids.add(nid)
                        node_copy = dict(n)
                        node_copy.setdefault("scope", scope)
                        all_nodes.append(node_copy)

        internal_nodes = self.storage.load_jsonl(self.config.internal_memory_dir / "nodes.jsonl")
        for n in internal_nodes:
            nid = n.get("id")
            if nid and nid not in seen_ids:
                seen_ids.add(nid)
                node_copy = dict(n)
                node_copy.setdefault("scope", "internal")
                all_nodes.append(node_copy)

        # Patch-derived fallback nodes are only relevant when nodes.jsonl was
        # never materialized (patch-only history); with a real graph file every
        # applied patch is already reflected there.
        patches_path = self.config.memory_dir / "patches.jsonl"
        patch_fallback_active = not (self.config.memory_dir / "nodes.jsonl").exists()
        for patch in self.storage.load_jsonl(patches_path) if patch_fallback_active else []:
            if patch.get("status") != "applied" or patch.get("operation") != "upsert_node":
                continue
            nid = patch.get("target")
            if not nid or nid in seen_ids:
                continue
            payload = patch.get("payload") or {}
            node_payload = payload.get("node") if isinstance(payload.get("node"), dict) else {}
            summary = node_payload.get("summary") or payload.get("summary") or patch.get("reason", "")
            seen_ids.add(nid)
            all_nodes.append({
                "id": nid,
                "type": node_payload.get("type") or patch.get("type", "fact"),
                "summary": summary,
                "evidence": node_payload.get("evidence") or patch.get("evidence", []),
                "status": node_payload.get("status", "verified"),
                "freshness": node_payload.get("freshness", ""),
                "trust": node_payload.get("trust", "verified"),
                "related_nodes": node_payload.get("related_nodes", []),
                "tags": node_payload.get("tags", []),
                "scope": "patch",
            })

        return all_nodes

    def _load_edges(self) -> List[Dict[str, Any]]:
        roots = getattr(self.config, "memory_roots", [self.config.root_dir])
        all_edges: List[Dict[str, Any]] = []
        for root in roots:
            edges_path = root / "memory" / "edges.jsonl"
            if edges_path.exists():
                all_edges.extend(self.storage.load_jsonl(edges_path))
        internal_edges = self.storage.load_jsonl(self.config.internal_memory_dir / "edges.jsonl")
        all_edges.extend(internal_edges)
        return all_edges


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
        return self.codebase_adapter.build_reverse_dependency_map(items_by_file)

    def traverse_dependents(
        self, start_files: Set[str], depth: int,
        reverse_map: Dict[str, Set[str]]
    ) -> Set[str]:
        return self.codebase_adapter.traverse_dependents(start_files, depth, reverse_map)

    def traverse_dependencies(self, start_files: Set[str], depth: int,
                              items_by_file: Dict[str, Dict[str, Any]]) -> Set[str]:
        return self.codebase_adapter.traverse_dependencies(start_files, depth, items_by_file)

    def search_memory(
        self,
        query: str,
        depth: int = 1,
        semantic: bool = False,
        hybrid: bool = False,
        all_time: bool = False,
    ) -> List[Dict[str, Any]]:
        current_version = getattr(self.repository, "get_version_hash", lambda: "")()
        if current_version and current_version != self._cache_version:
            self._query_cache.clear()
            self._cache_version = current_version
            
        cache_key = (query, depth, semantic, hybrid, all_time)
        if cache_key in self._query_cache:
            return self._query_cache[cache_key]
            
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
        
        def _confidence_multiplier(node: Dict[str, Any]) -> float:
            # Confidence-aware ranking (Phase 3): a 0.2-confidence draft should
            # not outrank a verified fact on lexical overlap alone. Full
            # confidence = 1.0x, zero confidence = 0.5x — downrank, never hide.
            try:
                conf = float(node.get("confidence", 1.0) or 1.0)
            except (TypeError, ValueError):
                conf = 1.0
            return 0.5 + 0.5 * max(0.0, min(1.0, conf))

        # Helper for lexical search
        def _run_lexical_search() -> Dict[str, float]:
            res_scores = {}
            sqlite_results = []
            if getattr(self.repository, "indexer", None) and hasattr(self.repository.indexer, "search_graph_nodes"):
                safe_query = re.sub(r'[^\w\s]', ' ', query).strip()
                if safe_query:
                    fts_query = " ".join([w for w in safe_query.split()])
                    if fts_query:
                        if not query.endswith(' '):
                            fts_query += '*'
                        sqlite_results = self.repository.indexer.search_graph_nodes(fts_query, limit=100)

            if sqlite_results:
                for res in sqlite_results:
                    nid = res["id"]
                    score = res.get("search_score", 1.0)
                    if res.get("status") in ["stale", "superseded"]:
                        score *= 0.5
                    elif res.get("status") == "archived":
                        score *= 0.1
                    score *= _confidence_multiplier(nodes_by_id.get(nid, res))
                    res_scores[nid] = score
            else:
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
                        score += VERBATIM_QUERY_SCORE
                    if query_tokens:
                        node_tokens = tokenize(full_text)
                        overlap = query_tokens.intersection(node_tokens)
                        if len(query_tokens) > 0:
                            score += (len(overlap) / len(query_tokens)) * 5.0
                    if score >= 1.5:
                        if node.get("status") in ["stale", "superseded"]:
                            score *= 0.5
                        elif node.get("status") == "archived":
                            score *= 0.1
                        score *= _confidence_multiplier(node)
                        res_scores[node_id] = score
            return res_scores

        # Helper for semantic search
        def _run_semantic_search(force_embed: bool = False) -> Dict[str, float]:
            sem_scores = {}
            try:
                from memory_os.toolkit.embedding_provider import EmbeddingProvider, _cosine
                provider = EmbeddingProvider(config=self.config)
                if force_embed:
                    vec_cache = provider.embed_nodes(nodes)
                else:
                    vec_cache = provider._load_cache()
                    # If cache empty or misses many nodes, compute dynamically
                    if len(vec_cache) < len(nodes):
                        vec_cache = provider.embed_nodes(nodes)

                if len(vec_cache) >= 1:
                    q_vec = provider._embed(query)
                    if q_vec:
                        if hybrid:
                            threshold = 0.10
                        elif semantic:
                            threshold = getattr(self.config, "semantic_similarity_threshold", 0.6)
                        else:
                            threshold = getattr(self.config, "semantic_fallback_threshold", 0.15)
                        for node in nodes:
                            nid = node.get("id")
                            if nid and nid in vec_cache:
                                sim = _cosine(q_vec, vec_cache[nid])
                                if sim >= threshold:
                                    sem_scores[nid] = sim
            except Exception as _e:
                import sys as _sys
                print(f'Ignored exception: {_e}', file=_sys.stderr)
            return sem_scores

        if hybrid:
            # Hybrid Retrieval with Reciprocal Rank Fusion (RRF, Phase M0.2)
            lexical_candidates = _run_lexical_search()
            semantic_candidates = _run_semantic_search(force_embed=True)

            lex_sorted = sorted(lexical_candidates.items(), key=lambda x: x[1], reverse=True)
            sem_sorted = sorted(semantic_candidates.items(), key=lambda x: x[1], reverse=True)

            lex_ranks = {nid: rank + 1 for rank, (nid, _) in enumerate(lex_sorted)}
            sem_ranks = {nid: rank + 1 for rank, (nid, _) in enumerate(sem_sorted)}

            all_cands = set(lex_ranks.keys()) | set(sem_ranks.keys())
            for nid in all_cands:
                rrf = 0.0
                if nid in lex_ranks:
                    rrf += 1.0 / (60.0 + lex_ranks[nid])
                if nid in sem_ranks:
                    rrf += 1.0 / (60.0 + sem_ranks[nid])

                node = nodes_by_id.get(nid, {})
                score = rrf * 100.0 * _confidence_multiplier(node)
                matched_node_ids.add(nid)
                node_scores[nid] = score
                if nid in nodes_by_id:
                    nodes_by_id[nid]["score_breakdown"] = {
                        "rrf": round(rrf * 100.0, 3),
                        "lex_rank": lex_ranks.get(nid),
                        "sem_rank": sem_ranks.get(nid),
                        "cosine_sim": round(semantic_candidates.get(nid, 0.0), 3),
                    }
        elif semantic:
            # Forced semantic search
            sem_scores = _run_semantic_search(force_embed=True)
            for nid, sim in sem_scores.items():
                matched_node_ids.add(nid)
                node = nodes_by_id.get(nid, {})
                node_scores[nid] = sim * 9.0 * _confidence_multiplier(node)
        else:
            # Default lexical search with semantic fallback if 0 matches
            lex_scores = _run_lexical_search()
            for nid, score in lex_scores.items():
                matched_node_ids.add(nid)
                node_scores[nid] = score

            if not matched_node_ids:
                sem_scores = _run_semantic_search(force_embed=False)
                for nid, sim in sem_scores.items():
                    matched_node_ids.add(nid)
                    node = nodes_by_id.get(nid, {})
                    node_scores[nid] = sim * 9.0 * _confidence_multiplier(node)

        # Bi-Temporal validity checks (valid_from / valid_until)
        if not all_time:
            now_iso = datetime.now(timezone.utc).isoformat()
            for nid in list(matched_node_ids):
                node = nodes_by_id.get(nid, {})
                v_until = node.get("valid_until", "")
                if v_until and now_iso > v_until:
                    # Expired fact downranked
                    node_scores[nid] *= 0.1
                    node["temporal_status"] = "expired"
                v_from = node.get("valid_from", "")
                if v_from and now_iso < v_from:
                    # Future fact downranked
                    node_scores[nid] *= 0.1
                    node["temporal_status"] = "future"

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

        final_results = matched_nodes + results_code
        self._query_cache[cache_key] = final_results
        
        # Access tracking — update node_stats.json (works without indexer).
        matched_ids = [n["id"] for n in matched_nodes if "id" in n]
        if matched_ids:
            if self.repository and self.repository.indexer:
                getattr(self.repository.indexer, "log_node_access", lambda x: None)(matched_ids)
            try:
                stats_path = self.config.memory_dir / "node_stats.json"
                NodeStatsStore(stats_path, self.storage).record_access(matched_ids)
            except Exception as _e:
                import sys as _sys
                print(f'Ignored exception: {_e}', file=_sys.stderr)

        return final_results

    def incremental_sync(self, patch: Any) -> None:
        """Incrementally update FTS index and invalidate embedding cache for touched node/edge IDs."""
        from memory_os.core.core import MemoryOS
        db = MemoryOS(self.config)
        
        # 1. Determine which nodes/edges were touched
        touched_node_ids = set()
        
        if patch.operation in ("upsert_node", "update_node", "deprecate_node"):
            if patch.target:
                touched_node_ids.add(patch.target)
        elif patch.operation == "replace_nodes":
            db_summaries = db.get_graph_node_summaries()

            self.repository.sync_graph_nodes()
            nodes = self._load_nodes()
            nodes_by_id = {n["id"]: n for n in nodes if n.get("id")}

            invalidated_ids = []
            for nid in db_summaries:
                if nid not in nodes_by_id:
                    invalidated_ids.append(nid)
            for nid, node in nodes_by_id.items():
                if nid in db_summaries and db_summaries[nid] != node.get("summary", ""):
                    invalidated_ids.append(nid)
            if invalidated_ids:
                from memory_os.toolkit.embedding_provider import EmbeddingProvider
                provider = EmbeddingProvider(config=self.config)
                provider.invalidate_embeddings(invalidated_ids)
            return

        elif patch.operation == "upsert_edge":
            db.insert_graph_edge(patch.source, patch.target, patch.type)
            return
        elif patch.operation == "delete_edge_soft":
            db.delete_graph_edge(patch.source, patch.target, patch.type)
            return
        elif patch.operation == "replace_edges":
            self.repository.sync_graph_edges()
            return
        else:
            return

        # 2. Process touched nodes
        if not touched_node_ids:
            return

        nodes = self._load_nodes()
        nodes_by_id = {n["id"]: n for n in nodes if n.get("id")}

        old_summaries = db.get_graph_node_summaries(list(touched_node_ids))

        for nid in touched_node_ids:
            node = nodes_by_id.get(nid)
            if node:
                tags_str = ",".join(node.get("tags", [])) if node.get("tags") else None
                db.insert_graph_node(
                    node_id=nid,
                    node_type=node.get("type", "fact"),
                    summary=node.get("summary", ""),
                    status=node.get("status", "draft"),
                    freshness=node.get("freshness", ""),
                    trust=node.get("trust", "unverified"),
                    tags=tags_str,
                )
            else:
                db.delete_graph_node(nid)

        invalidated_ids = []
        for nid in touched_node_ids:
            node = nodes_by_id.get(nid)
            if not node:
                invalidated_ids.append(nid)
            elif nid in old_summaries and old_summaries[nid] != node.get("summary", ""):
                invalidated_ids.append(nid)

        if invalidated_ids:
            from memory_os.toolkit.embedding_provider import EmbeddingProvider
            provider = EmbeddingProvider(config=self.config)
            provider.invalidate_embeddings(invalidated_ids)
