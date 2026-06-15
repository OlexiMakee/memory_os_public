"""
EmbeddingProvider — Stage 1 of the link-infer cascade.

Uses Ollama (already a project dependency) with nomic-embed-text to build
a local vector index of memory nodes, then finds K-nearest neighbours by
cosine similarity and proposes edges.

Embeddings are cached in memory/embeddings.jsonl so each node is embedded
only once.  The ResourceGuard is checked before every Ollama call so the
host machine stays within safe thermal limits.

Required: Ollama running locally with nomic-embed-text pulled:
    ollama pull nomic-embed-text
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from memory_os.core.config import MemoryOSConfig
from memory_os.core.logger import get_logger
from memory_os.core.models import MemoryEdge
from memory_os.core.resource_guard import ResourceGuard

logger = get_logger(__name__)

DEFAULT_MODEL   = "nomic-embed-text"
CACHE_FILENAME  = "embeddings.jsonl"


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class EmbeddingProvider:
    """
    Implements the Stage-1 interface expected by link_inferrer.infer_embeddings().
    """

    def __init__(
        self,
        config: Optional[MemoryOSConfig] = None,
        model: str = DEFAULT_MODEL,
        guard: Optional[ResourceGuard] = None,
    ):
        self.config = config
        self.model  = model
        self.guard  = guard or ResourceGuard()
        self._cache_path: Optional[Path] = (
            Path(config.memory_dir) / CACHE_FILENAME if config else None
        )

    # ------------------------------------------------------------------
    # Cache I/O
    # ------------------------------------------------------------------

    def _load_cache(self) -> Dict[str, List[float]]:
        cache: Dict[str, List[float]] = {}
        if self._cache_path and self._cache_path.exists():
            with open(self._cache_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        cache[entry["id"]] = entry["vector"]
                    except (KeyError, json.JSONDecodeError):
                        pass
        return cache

    def _append_to_cache(self, node_id: str, vector: List[float]) -> None:
        if not self._cache_path:
            return
        entry = {"id": node_id, "model": self.model, "vector": vector}
        with open(self._cache_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    def _embed(self, text: str) -> Optional[List[float]]:
        """Call Ollama library for a single embedding. Returns None on failure."""
        try:
            import ollama  # already in project dependencies
            response = ollama.embeddings(model=self.model, prompt=text)
            return response.get("embedding") or response.get("embeddings")
        except Exception as exc:
            logger.warning(f"[EmbeddingProvider] Ollama call failed: {exc}")
            return None

    def embed_nodes(self, nodes: List[dict]) -> Dict[str, List[float]]:
        """
        Embed all nodes, using cache for previously seen ones.
        Checks ResourceGuard before each Ollama call.
        """
        cache = self._load_cache()
        new_nodes = [n for n in nodes if n["id"] not in cache]

        if new_nodes:
            logger.info(f"[EmbeddingProvider] Embedding {len(new_nodes)} new nodes "
                        f"({len(cache)} already cached) via {self.model}...")

        for i, node in enumerate(new_nodes):
            # Thermal check before each call
            if not self.guard.is_safe():
                snap = self.guard.snapshot()
                logger.warning(
                    f"[EmbeddingProvider] System {snap.level} "
                    f"(CPU {snap.cpu:.0f}% RAM {snap.ram:.0f}%"
                    + (f" {snap.temp:.0f}°C" if snap.temp else "")
                    + ") — waiting..."
                )
                ok = self.guard.wait_until_safe()
                if not ok:
                    logger.error("[EmbeddingProvider] Timeout waiting for system to cool. "
                                 "Stopping embedding early.")
                    break

            text = node.get("summary", "")
            if not text:
                continue

            vec = self._embed(text)
            if vec:
                cache[node["id"]] = vec
                self._append_to_cache(node["id"], vec)

            # Small breath between calls to avoid thermal spike
            if i < len(new_nodes) - 1:
                time.sleep(0.05)

        return cache

    # ------------------------------------------------------------------
    # Edge inference
    # ------------------------------------------------------------------

    def infer_edges(
        self,
        nodes: List[dict],
        existing_pairs: Set[Tuple[str, str]],
        top_k: int = 5,
        min_cosine: float = 0.75,
    ) -> List[MemoryEdge]:
        """
        Builds/loads embeddings, finds K-nearest neighbours,
        and returns candidate MemoryEdge objects.
        """
        cache = self.embed_nodes(nodes)

        # Only consider nodes that were successfully embedded
        embedded = [(n["id"], cache[n["id"]]) for n in nodes if n["id"] in cache]
        if len(embedded) < 2:
            logger.info("[EmbeddingProvider] Not enough embedded nodes for KNN.")
            return []

        ids  = [item[0] for item in embedded]
        vecs = [item[1] for item in embedded]

        edges: List[MemoryEdge] = []
        seen: Set[Tuple[str, str]] = set()

        for i, nid_a in enumerate(ids):
            scored: List[Tuple[float, str]] = []
            for j, nid_b in enumerate(ids):
                if i == j:
                    continue
                sim = _cosine(vecs[i], vecs[j])
                if sim >= min_cosine:
                    scored.append((sim, nid_b))

            scored.sort(reverse=True)

            for sim, nid_b in scored[:top_k]:
                if (nid_a, nid_b) in existing_pairs or (nid_b, nid_a) in existing_pairs:
                    continue
                canonical: Tuple[str, str] = tuple(sorted([nid_a, nid_b]))  # type: ignore[assignment]
                if canonical in seen:
                    continue
                seen.add(canonical)
                edges.append(MemoryEdge(
                    source=nid_a,
                    target=nid_b,
                    type="depends_on",
                    confidence=round(sim, 3),
                    reason=f"embedding:cosine={sim:.3f}",
                ))

        logger.info(f"[EmbeddingProvider] {len(edges)} embedding-similarity edges found.")
        return edges
