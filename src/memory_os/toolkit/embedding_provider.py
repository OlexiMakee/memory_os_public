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
        self.guard  = guard or ResourceGuard(config=config)
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

    def invalidate_embeddings(self, node_ids: List[str] | Set[str]) -> None:
        """Remove embedding cache entries for the given node IDs."""
        if not self._cache_path or not self._cache_path.exists():
            return
        node_ids_set = set(node_ids)
        lines = []
        with open(self._cache_path, "r", encoding="utf-8") as f:
            for line in f:
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                try:
                    entry = json.loads(line_stripped)
                    if entry.get("id") not in node_ids_set:
                        lines.append(line)
                except Exception as _e:
                    import sys as _sys
                    print(f'Ignored exception: {_e}', file=_sys.stderr)
        with open(self._cache_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    @staticmethod
    def _local_fast_vector(text: str, dim: int = 128) -> List[float]:
        """
        Fast zero-dependency deterministic subword/char-trigram hashing vectorizer.
        L2-normalized 128-dimensional representation that captures semantic and
        morphological similarities across languages (e.g. Ukrainian and English).
        """
        if not text:
            return [0.0] * dim
        import hashlib
        import re

        COMMON_TECH_MAP = {
            "пайтон": "python",
            "пітон": "python",
            "бот": "bot",
            "ботів": "bot",
            "боти": "bot",
            "телеграм": "telegram",
            "кубернетіс": "kubernetes",
            "кубер": "k8s kubernetes",
            "скрейпінг": "scrape scraping",
            "парсинг": "parse parsing scraper",
            "парсер": "parser scraping",
            "докер": "docker",
            "джанго": "django",
            "фласк": "flask",
            "фастапі": "fastapi",
            "реакт": "react",
            "тайпскрипт": "typescript",
            "раст": "rust",
            "фріланс": "freelance",
            "вакансія": "vacancy job",
            "робота": "job career",
            "бекенд": "backend",
            "фронтенд": "frontend",
        }

        vec = [0.0] * dim
        clean = text.lower().strip()
        words = [w for w in re.split(r'\W+', clean) if len(w) > 1]

        # Expand bilingual synonyms
        expanded_words = list(words)
        for w in words:
            if w in COMMON_TECH_MAP:
                expanded_words.extend(COMMON_TECH_MAP[w].split())

        # Word-level features
        for w in expanded_words:
            h = int(hashlib.md5(w.encode("utf-8")).hexdigest(), 16)
            idx = h % dim
            sign = 1.0 if (h // dim) % 2 == 0 else -1.0
            vec[idx] += 2.0 * sign

        # Char-trigram features for morphological / substring matching
        if len(clean) >= 3:
            for i in range(len(clean) - 2):
                tri = clean[i:i+3]
                h = int(hashlib.sha256(tri.encode("utf-8")).hexdigest(), 16)
                idx = h % dim
                sign = 1.0 if (h // dim) % 2 == 0 else -1.0
                vec[idx] += 1.0 * sign

        # L2-normalize
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0.0:
            vec = [x / norm for x in vec]
        return vec

    def _embed(self, text: str) -> Optional[List[float]]:
        """Embed text via llama-server /embedding or Ollama HTTP API, falling back to local vectorizer."""
        import json
        import os
        import urllib.request

        llama_server_url = os.environ.get("LLAMA_SERVER_URL")
        if llama_server_url:
            url = f"{llama_server_url.rstrip('/')}/embedding"
            payload = json.dumps({"content": text}).encode("utf-8")
        else:
            host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
            url = f"{host}/api/embeddings"
            payload = json.dumps({"model": self.model, "prompt": text}).encode("utf-8")

        try:
            req = urllib.request.Request(
                url, data=payload, headers={"Content-Type": "application/json"}
            )
            # Use quick timeout to detect if local daemon is not running
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                result = json.loads(resp.read())

            if isinstance(result, list) and len(result) > 0:
                vec = result[0].get("embedding")
            elif isinstance(result, dict):
                vec = result.get("embedding") or result.get("embeddings")
            else:
                vec = None

            if isinstance(vec, list) and len(vec) > 0 and isinstance(vec[0], list):
                vec = vec[0]

            if isinstance(vec, list):
                return vec
        except Exception:
            pass

        # Fallback to zero-dependency local deterministic subword vector
        return self._local_fast_vector(text)

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
