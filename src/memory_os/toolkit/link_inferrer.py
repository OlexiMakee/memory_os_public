"""
Link Inferrer — automatic edge discovery for the Memory OS graph.

Inference cascade (method="cascade", the new default):
  Stage 0 — algorithmic, zero cost, zero heat:
              BM25 inverted-index text similarity
              structural ID-hierarchy edges
              tag co-occurrence edges
              temporal-proximity edges
  Stage 1 — local embedding model, opt-in (resource_mode≥normal) [stub — coming next]
  Stage 2 — local LM edge-type refinement   (resource_mode=max)  [stub — coming next]
  Stage 3 — cloud LLM on remaining unlinked nodes (--method llm/both)

Legacy method aliases: text, llm, both  (still work as before).
resource_mode: quiet | normal | max  (read from config, overridable via CLI flag).
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from memory_os.core.config import MemoryOSConfig
from memory_os.core.logger import get_logger
from memory_os.core.models import MemoryEdge

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# LLM system prompt (Stage 3 — unchanged)
# ---------------------------------------------------------------------------

LINK_INFER_SYSTEM_PROMPT = """\
You are a knowledge graph edge inferrer for Memory OS.

You receive a list of memory nodes (id + summary). Your task is to find \
meaningful relationships between them and output edges.

Edge types available:
- depends_on   : A needs B to be understood / function
- triggers     : A causes or initiates B
- configures   : A sets up parameters/behaviour of B
- contains     : A is a parent/container of B
- refutes      : A contradicts or supersedes B

Rules:
1. Only output edges where the relationship is CLEAR and NON-TRIVIAL.
2. Do NOT output edges that already exist (provided in EXISTING EDGES).
3. Prefer specificity — if A mentions B by name or concept, that is a strong signal.
4. Output ONLY a raw JSON array of edge objects. No markdown, no explanation.

Schema:
[
  {"source": "node_id", "target": "node_id", "type": "edge_type", "reason": "one sentence why"}
]
"""

# ---------------------------------------------------------------------------
# Stage 0 helpers — tokenizer, BM25, edge-type patterns
# ---------------------------------------------------------------------------

_STOPWORDS: Set[str] = {
    "this", "that", "with", "from", "have", "will", "been", "into",
    "more", "some", "when", "what", "which", "then", "than", "also",
    "each", "they", "their", "there", "about", "after", "where",
    "other", "used", "uses", "note", "your", "object", "value",
    "these", "those", "param", "field", "list", "type", "data",
    "node", "edge", "memory", "agent",
}

def _tokenize(text: str) -> List[str]:
    """Lowercase words ≥4 chars, minus stopwords. Shared by all Stage-0 methods."""
    words = re.findall(r"[a-zа-яіїєёa-z]{4,}", text.lower())
    return [w for w in words if w not in _STOPWORDS]


class _BM25:
    """
    Minimal BM25 implementation — no external dependencies.
    k1=1.5, b=0.75 are standard defaults (Robertson & Zaragoza 2009).
    """
    k1 = 1.5
    b   = 0.75

    def __init__(self, corpus: List[List[str]]):
        self.N = len(corpus)
        self.avgdl = sum(len(d) for d in corpus) / max(self.N, 1)
        self.df: Dict[str, int] = defaultdict(int)
        self.tf: List[Dict[str, int]] = []
        for doc in corpus:
            freq: Dict[str, int] = defaultdict(int)
            for tok in doc:
                freq[tok] += 1
            self.tf.append(dict(freq))
            for tok in freq:
                self.df[tok] += 1

    def idf(self, tok: str) -> float:
        df = self.df.get(tok, 0)
        return math.log((self.N - df + 0.5) / (df + 0.5) + 1)

    def score(self, doc_idx: int, query_tokens: List[str]) -> float:
        tf_d = self.tf[doc_idx]
        dl = sum(tf_d.values())
        s = 0.0
        for tok in query_tokens:
            if tok not in tf_d:
                continue
            f = tf_d[tok]
            s += self.idf(tok) * f * (self.k1 + 1) / (
                f + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
            )
        return s


def _build_inverted(tokenized: List[List[str]]) -> Dict[str, List[int]]:
    inv: Dict[str, List[int]] = defaultdict(list)
    for i, tokens in enumerate(tokenized):
        for tok in set(tokens):
            inv[tok].append(i)
    return inv


# Patterns to infer edge type from the source node's summary.
_RE_TRIGGERS   = re.compile(r"\b(trigger|cause|initiat|launch|invok|activat|call|emit)\w*\b", re.I)
_RE_CONFIGURES = re.compile(r"\b(configur|set[s ]up|control|parameter|option|setting|tune)\w*\b", re.I)
_RE_REFUTES    = re.compile(r"\b(refut|contradict|supersed|replac|overrid|deprecat|negate)\w*\b", re.I)
_RE_SECURES    = re.compile(r"\b(secur|authenticat|authoriz|protect|encrypt|validat)\w*\b", re.I)
_RE_CONTAINS   = re.compile(r"\b(contain|includ|part of|consist|compris)\w*\b", re.I)


def _infer_edge_type(summary_a: str, id_a: str, id_b: str) -> str:
    """
    Best-effort edge type from source node's summary text.
    Falls back to depends_on when no pattern matches.
    """
    # ID-hierarchy takes priority: if id_a starts with id_b → id_b contains id_a
    parts_a = re.split(r"[._\-/]", id_a)
    parts_b = re.split(r"[._\-/]", id_b)
    if len(parts_b) < len(parts_a) and parts_a[: len(parts_b)] == parts_b:
        return "contains"

    if _RE_REFUTES.search(summary_a):
        return "refutes"
    if _RE_TRIGGERS.search(summary_a):
        return "triggers"
    if _RE_CONFIGURES.search(summary_a):
        return "configures"
    if _RE_SECURES.search(summary_a):
        return "secures"
    if _RE_CONTAINS.search(summary_a):
        return "contains"
    return "depends_on"


def _parse_ts(freshness: str) -> Optional[float]:
    """Try common ISO-ish formats; return None if unparseable."""
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(freshness[:len(fmt)], fmt).timestamp()
        except (ValueError, TypeError):
            continue
    return None


# ---------------------------------------------------------------------------
# Stage 0 — algorithmic inference
# ---------------------------------------------------------------------------

def infer_bm25(
    nodes: List[dict],
    existing_pairs: Set[Tuple[str, str]],
    top_k: int = 5,
    min_score: float = 1.5,
) -> List[MemoryEdge]:
    """
    BM25 text similarity via inverted index.
    O(n·k·d) instead of O(n²) — scales to thousands of nodes without heat.

    For each node A, ranks all other nodes by BM25(their summary | A's tokens).
    Keeps the top_k candidates above min_score per node.
    """
    if len(nodes) < 2:
        return []

    tokenized = [_tokenize(n.get("summary", "")) for n in nodes]
    bm25 = _BM25(tokenized)
    inv  = _build_inverted(tokenized)

    best: Dict[Tuple[str, str], Tuple[float, MemoryEdge]] = {}

    for i, node_a in enumerate(nodes):
        qtoks = tokenized[i]
        if not qtoks:
            continue

        # Candidate indices from inverted index only (skip full O(n) scan)
        candidate_idxs: Set[int] = set()
        for tok in qtoks:
            for idx in inv.get(tok, []):
                if idx != i:
                    candidate_idxs.add(idx)

        scored = [
            (bm25.score(j, qtoks), j)
            for j in candidate_idxs
        ]
        scored.sort(reverse=True)

        for score, j in scored[:top_k]:
            if score < min_score:
                break
            node_b = nodes[j]
            src, tgt = node_a["id"], node_b["id"]
            if (src, tgt) in existing_pairs or (tgt, src) in existing_pairs:
                continue
            canonical: Tuple[str, str] = tuple(sorted([src, tgt]))  # type: ignore[assignment]
            if canonical in best and best[canonical][0] >= score:
                continue
            etype = _infer_edge_type(node_a.get("summary", ""), src, tgt)
            edge = MemoryEdge(
                source=src,
                target=tgt,
                type=etype,
                confidence=min(round(score / 12.0, 2), 0.95),
                reason=f"bm25:{score:.1f}",
            )
            best[canonical] = (score, edge)

    return [e for _, e in best.values()]


def infer_structural(
    nodes: List[dict],
    existing_pairs: Set[Tuple[str, str]],
) -> List[MemoryEdge]:
    """
    ID-hierarchy edges: if B's ID segments are a strict prefix of A's ID segments,
    B contains A.  e.g.  feature.auth  →contains→  feature.auth.login
    """
    edges: List[MemoryEdge] = []
    sep = re.compile(r"[._\-/]")

    parts_map = {n["id"]: sep.split(n["id"]) for n in nodes}

    for node_a in nodes:
        pa = parts_map[node_a["id"]]
        for node_b in nodes:
            if node_a["id"] == node_b["id"]:
                continue
            pb = parts_map[node_b["id"]]
            # B contains A: B's parts are a strict proper prefix of A's parts
            if len(pb) < len(pa) and pa[: len(pb)] == pb:
                src, tgt = node_b["id"], node_a["id"]
                if (src, tgt) in existing_pairs:
                    continue
                edges.append(MemoryEdge(
                    source=src,
                    target=tgt,
                    type="contains",
                    confidence=1.0,
                    reason="structural:id-hierarchy",
                ))
                existing_pairs.add((src, tgt))

    return edges


def infer_tags(
    nodes: List[dict],
    existing_pairs: Set[Tuple[str, str]],
    min_shared: int = 1,
) -> List[MemoryEdge]:
    """
    Tag co-occurrence: nodes sharing ≥min_shared tags are topically related.
    Uses co_tagged edge type (tags are already specific, so 1 shared tag is enough).
    """
    edges: List[MemoryEdge] = []
    tag_map: Dict[str, Set[str]] = {}
    for n in nodes:
        tags = {t.lower() for t in n.get("tags", []) if len(t) >= 3}
        tag_map[n["id"]] = tags

    seen: Set[Tuple[str, str]] = set()
    for i, node_a in enumerate(nodes):
        ta = tag_map[node_a["id"]]
        if not ta:
            continue
        for node_b in nodes[i + 1 :]:
            tb = tag_map[node_b["id"]]
            shared = ta & tb
            if len(shared) < min_shared:
                continue
            src, tgt = node_a["id"], node_b["id"]
            canonical: Tuple[str, str] = tuple(sorted([src, tgt]))  # type: ignore[assignment]
            if canonical in seen:
                continue
            if (src, tgt) in existing_pairs or (tgt, src) in existing_pairs:
                continue
            seen.add(canonical)
            edges.append(MemoryEdge(
                source=src,
                target=tgt,
                type="co_tagged",
                confidence=min(0.4 + 0.15 * len(shared), 0.9),
                reason=f"shared-tags:{','.join(sorted(shared))}",
            ))

    return edges


def infer_temporal(
    nodes: List[dict],
    existing_pairs: Set[Tuple[str, str]],
    window_hours: float = 48.0,
    min_bm25: float = 0.5,
) -> List[MemoryEdge]:
    """
    Temporal proximity: nodes created within window_hours that also share
    BM25 similarity above min_bm25 are likely co_created.
    The BM25 guard prevents spurious edges between unrelated contemporaneous nodes.
    """
    window_secs = window_hours * 3600

    # Only process nodes with parseable timestamps
    timed: List[Tuple[float, dict]] = []
    for n in nodes:
        ts = _parse_ts(n.get("freshness", ""))
        if ts is not None:
            timed.append((ts, n))

    if len(timed) < 2:
        return []

    timed.sort(key=lambda x: x[0])

    # Build a small BM25 index for just the timed nodes
    timed_nodes = [n for _, n in timed]
    tokenized   = [_tokenize(n.get("summary", "")) for n in timed_nodes]
    bm25        = _BM25(tokenized)

    edges: List[MemoryEdge] = []
    seen: Set[Tuple[str, str]] = set()

    for i, (ts_a, node_a) in enumerate(timed):
        for j in range(i + 1, len(timed)):
            ts_b, node_b = timed[j]
            if ts_b - ts_a > window_secs:
                break  # sorted by time — no need to look further
            src, tgt = node_a["id"], node_b["id"]
            canonical: Tuple[str, str] = tuple(sorted([src, tgt]))  # type: ignore[assignment]
            if canonical in seen:
                continue
            if (src, tgt) in existing_pairs or (tgt, src) in existing_pairs:
                continue
            # BM25 guard: require some topical overlap
            score = bm25.score(j, tokenized[i])
            if score < min_bm25:
                continue
            seen.add(canonical)
            edges.append(MemoryEdge(
                source=src,
                target=tgt,
                type="co_created",
                confidence=min(round(score / 8.0, 2), 0.7),
                reason=f"temporal:{abs(ts_b - ts_a) / 3600:.1f}h apart",
            ))

    return edges


# ---------------------------------------------------------------------------
# Stage 1 stub — local embedding model (M4 Neural Engine / RTX 3060 Ti CUDA)
# ---------------------------------------------------------------------------

def infer_embeddings(
    nodes: List[dict],
    existing_pairs: Set[Tuple[str, str]],
    top_k: int = 5,
    min_cosine: float = 0.75,
) -> List[MemoryEdge]:
    """
    Placeholder for Stage 1: sentence-transformer cosine similarity.

    M4:  sentence-transformers + Metal  (~15ms/node, ~22MB model)
    GPU: FAISS + CUDA on RTX 3060 Ti    (~1ms/node, larger models)

    Returns [] until a local embedding provider is configured.
    """
    try:
        from memory_os.toolkit.embedding_provider import EmbeddingProvider  # type: ignore
        provider = EmbeddingProvider()
        return provider.infer_edges(nodes, existing_pairs, top_k=top_k, min_cosine=min_cosine)
    except ImportError:
        return []


# ---------------------------------------------------------------------------
# Stage 2 stub — local LM for edge-type refinement
# ---------------------------------------------------------------------------

def refine_edge_types_lm(edges: List[MemoryEdge]) -> List[MemoryEdge]:
    """
    Placeholder for Stage 2: small local LM (qwen2.5:0.5b via Ollama) to
    reclassify depends_on edges into more specific types.

    Returns edges unchanged until a local LM provider is configured.
    """
    try:
        from memory_os.toolkit.local_lm_refiner import refine  # type: ignore
        return refine(edges)
    except ImportError:
        return edges


# ---------------------------------------------------------------------------
# Stage 3 — Cloud LLM batch inference (unchanged)
# ---------------------------------------------------------------------------

def infer_llm(
    nodes: List[dict],
    existing_pairs: Set[Tuple[str, str]],
    provider: Optional[str] = None,
    model: Optional[str] = None,
    batch_size: int = 60,
) -> List[MemoryEdge]:
    """Return candidate edges via LLM semantic analysis."""
    from memory_os.core.llm_service import _call_llm_direct

    all_edges: List[MemoryEdge] = []

    def _node_line(n: dict) -> str:
        summary = n["summary"][:200].replace("\n", " ")
        return f'{n["id"]}: {summary}'

    existing_lines = [f"{s} -> {t}" for s, t in sorted(existing_pairs)[:200]]

    for i in range(0, len(nodes), batch_size):
        batch = nodes[i : i + batch_size]
        node_block = "\n".join(_node_line(n) for n in batch)
        all_ids    = "\n".join(n["id"] for n in nodes)

        user_message = (
            f"ALL NODE IDs (for reference):\n{all_ids}\n\n"
            f"NODES TO ANALYSE (batch {i // batch_size + 1}):\n{node_block}\n\n"
            f"EXISTING EDGES (do not repeat):\n" + "\n".join(existing_lines[:100])
        )

        logger.info(f"[LinkInferrer] LLM batch {i // batch_size + 1}: {len(batch)} nodes")

        try:
            raw = _call_llm_direct(
                user_message=user_message,
                system_prompt=LINK_INFER_SYSTEM_PROMPT,
                provider=provider,
                model=model,
            )
            raw = raw.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)

            proposals = json.loads(raw)
            if not isinstance(proposals, list):
                logger.warning("[LinkInferrer] LLM returned non-list, skipping batch")
                continue

            # Collect valid node IDs for phantom-edge guard
            valid_ids = {n["id"] for n in nodes}

            for p in proposals:
                src   = p.get("source", "")
                tgt   = p.get("target", "")
                etype = p.get("type", "depends_on")
                reason = p.get("reason", "llm-infer")

                if not src or not tgt or src == tgt:
                    continue
                # Guard: skip edges referencing non-existent nodes
                if src not in valid_ids or tgt not in valid_ids:
                    logger.warning(f"[LinkInferrer] LLM proposed phantom edge {src}→{tgt}, skipping.")
                    continue
                if (src, tgt) in existing_pairs:
                    continue

                all_edges.append(MemoryEdge(
                    source=src,
                    target=tgt,
                    type=etype,
                    confidence=0.8,
                    reason=reason,
                ))

        except (json.JSONDecodeError, KeyError) as exc:
            logger.error(f"[LinkInferrer] Failed to parse LLM response: {exc}")
        except RuntimeError as exc:
            logger.error(f"[LinkInferrer] LLM call failed: {exc}")
            raise

    return all_edges


# ---------------------------------------------------------------------------
# Legacy text-matching (kept for --method text backward compatibility)
# ---------------------------------------------------------------------------

def _id_keywords(node_id: str) -> Set[str]:
    parts = re.split(r"[._\-/]", node_id.lower())
    skip = {
        "notion", "page", "home", "entry", "database", "status", "verified", "fact",
        "book", "books", "film", "films", "game", "games", "idea", "ideas",
        "plan", "wiki", "team", "demo", "refs", "tbd", "real", "base",
        "core", "info", "data", "list", "item", "type", "work", "note",
        "tips", "docs", "tech", "prod", "mark",
    }
    return {p for p in parts if len(p) >= 5 and p not in skip}


def _text_score(node_a: dict, node_b: dict) -> float:
    id_kw_b = _id_keywords(node_b["id"])
    if not id_kw_b:
        return 0.0
    summary_a = node_a["summary"].lower()
    hits = sum(
        1 for kw in id_kw_b
        if re.search(rf"\b{re.escape(kw)}\b", summary_a)
    )
    return hits / len(id_kw_b)


def infer_text(
    nodes: List[dict],
    existing_pairs: Set[Tuple[str, str]],
    min_score: float = 0.3,
) -> List[MemoryEdge]:
    """Legacy text/ID keyword matching. Kept for --method text compatibility."""
    candidates: List[MemoryEdge] = []
    for a in nodes:
        for b in nodes:
            if a["id"] == b["id"]:
                continue
            if (a["id"], b["id"]) in existing_pairs:
                continue
            score = _text_score(a, b)
            if score >= min_score:
                candidates.append(MemoryEdge(
                    source=a["id"],
                    target=b["id"],
                    type="depends_on",
                    confidence=round(score, 2),
                    reason="text-match",
                ))
    seen: Dict[Tuple[str, str], MemoryEdge] = {}
    for e in candidates:
        key = tuple(sorted([e.source, e.target]))
        if key not in seen or e.confidence > seen[key].confidence:
            seen[key] = e
    return list(seen.values())


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

class LinkInferrer:
    def __init__(self, config: MemoryOSConfig):
        self.config = config
        self.nodes_path = Path(config.memory_dir) / "nodes.jsonl"
        self.edges_path = Path(config.memory_dir) / "edges.jsonl"

    def _load_nodes(self) -> List[dict]:
        nodes = []
        if self.nodes_path.exists():
            with open(self.nodes_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        nodes.append(json.loads(line))
        return nodes

    def _load_existing_pairs(self) -> Set[Tuple[str, str]]:
        pairs: Set[Tuple[str, str]] = set()
        if self.edges_path.exists():
            with open(self.edges_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        e = json.loads(line)
                        pairs.add((e["source"], e["target"]))
        return pairs

    def _write_edges(self, edges: List[MemoryEdge], existing_pairs: Set[Tuple[str, str]]) -> int:
        written = 0
        with open(self.edges_path, "a", encoding="utf-8") as f:
            for e in edges:
                if (e.source, e.target) not in existing_pairs:
                    f.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
                    existing_pairs.add((e.source, e.target))
                    written += 1
        return written

    def run(
        self,
        method: str = "cascade",
        resource_mode: Optional[str] = None,
        dry_run: bool = False,
        min_score: float = 0.3,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        batch_size: int = 60,
        exclude_types: Optional[Set[str]] = None,
    ) -> int:
        # resource_mode: CLI flag > config value > default "normal"
        rmode = resource_mode or self.config.resource_mode

        nodes = self._load_nodes()
        if not nodes:
            print("No nodes found in memory/nodes.jsonl")
            return 1

        # Filter before any processing
        before = len(nodes)
        nodes = [n for n in nodes if n.get("indexable", True)]
        if exclude_types:
            nodes = [n for n in nodes if n.get("type") not in exclude_types]
        skipped = before - len(nodes)
        if skipped:
            print(f"Skipped {skipped} nodes (indexable=false or excluded type).")

        existing_pairs = self._load_existing_pairs()
        committed_pairs = set(existing_pairs)
        print(f"Loaded {len(nodes)} nodes, {len(existing_pairs)} existing edges.")

        all_candidates: List[MemoryEdge] = []

        # ── Cascade (new default) ────────────────────────────────────────────
        if method == "cascade":
            # Stage 0: algorithmic — always runs, zero cost
            print("Stage 0: algorithmic inference (BM25, structural, tags, temporal)...")

            bm25_edges = infer_bm25(nodes, set(existing_pairs))
            print(f"  BM25:       {len(bm25_edges):4d} candidates")
            all_candidates.extend(bm25_edges)
            for e in bm25_edges:
                existing_pairs.add((e.source, e.target))

            struct_edges = infer_structural(nodes, set(existing_pairs))
            print(f"  Structural: {len(struct_edges):4d} candidates")
            all_candidates.extend(struct_edges)
            for e in struct_edges:
                existing_pairs.add((e.source, e.target))

            tag_edges = infer_tags(nodes, set(existing_pairs))
            print(f"  Tags:       {len(tag_edges):4d} candidates")
            all_candidates.extend(tag_edges)
            for e in tag_edges:
                existing_pairs.add((e.source, e.target))

            temporal_edges = infer_temporal(nodes, set(existing_pairs))
            print(f"  Temporal:   {len(temporal_edges):4d} candidates")
            all_candidates.extend(temporal_edges)
            for e in temporal_edges:
                existing_pairs.add((e.source, e.target))

            # Stage 1: local embeddings (normal / max)
            if rmode in ("normal", "max"):
                emb_edges = infer_embeddings(nodes, set(existing_pairs))
                if emb_edges:
                    print(f"  Embeddings: {len(emb_edges):4d} candidates")
                    all_candidates.extend(emb_edges)
                    for e in emb_edges:
                        existing_pairs.add((e.source, e.target))

            # Stage 2: local LM type refinement (max only)
            if rmode == "max":
                all_candidates = refine_edge_types_lm(all_candidates)

            # Stage 3: cloud LLM on nodes that Stage 0+1+2 left unlinked
            if rmode != "quiet":
                linked_ids: Set[str] = set()
                for e in all_candidates:
                    linked_ids.add(e.source)
                    linked_ids.add(e.target)
                for s, t in existing_pairs:
                    linked_ids.add(s)
                    linked_ids.add(t)
                unlinked = [n for n in nodes if n["id"] not in linked_ids]
                if unlinked and provider:
                    print(f"  Stage 3 LLM: {len(unlinked)} unlinked nodes...")
                    llm_edges = infer_llm(
                        unlinked, existing_pairs,
                        provider=provider, model=model, batch_size=batch_size,
                    )
                    print(f"  LLM:        {len(llm_edges):4d} candidates")
                    all_candidates.extend(llm_edges)

        # ── Legacy: text ─────────────────────────────────────────────────────
        elif method == "text":
            print("Running text matching (legacy)...")
            pass_num = 1
            while True:
                text_edges = infer_text(nodes, existing_pairs, min_score=min_score)
                if not text_edges:
                    if pass_num == 1:
                        print("  → 0 candidate edges")
                    break
                print(f"  → Pass {pass_num}: {len(text_edges)} candidate edges")
                all_candidates.extend(text_edges)
                for e in text_edges:
                    existing_pairs.add((e.source, e.target))
                    existing_pairs.add((e.target, e.source))
                pass_num += 1

        # ── Legacy: llm ──────────────────────────────────────────────────────
        elif method == "llm":
            print(f"Running LLM inference on all {len(nodes)} nodes...")
            llm_edges = infer_llm(
                nodes, existing_pairs,
                provider=provider, model=model, batch_size=batch_size,
            )
            print(f"  → {len(llm_edges)} candidate edges")
            all_candidates.extend(llm_edges)

        # ── Legacy: both ─────────────────────────────────────────────────────
        elif method == "both":
            print("Running text matching...")
            pass_num = 1
            while True:
                text_edges = infer_text(nodes, existing_pairs, min_score=min_score)
                if not text_edges:
                    if pass_num == 1:
                        print("  → 0 candidate edges from text")
                    break
                print(f"  → Pass {pass_num}: {len(text_edges)} candidate edges from text")
                all_candidates.extend(text_edges)
                for e in text_edges:
                    existing_pairs.add((e.source, e.target))
                    existing_pairs.add((e.target, e.source))
                pass_num += 1

            text_connected: Set[str] = set()
            for e in all_candidates:
                text_connected.add(e.source)
                text_connected.add(e.target)
            for s, t in existing_pairs:
                text_connected.add(s)
                text_connected.add(t)
            unlinked = [n for n in nodes if n["id"] not in text_connected]
            llm_nodes = unlinked if unlinked else nodes
            print(f"Running LLM inference on {len(llm_nodes)} under-connected nodes...")
            llm_edges = infer_llm(
                llm_nodes, existing_pairs,
                provider=provider, model=model, batch_size=batch_size,
            )
            print(f"  → {len(llm_edges)} candidate edges from LLM")
            all_candidates.extend(llm_edges)

        # ── Deduplicate final candidates ─────────────────────────────────────
        seen: Dict[Tuple[str, str], MemoryEdge] = {}
        for e in all_candidates:
            key = (e.source, e.target)
            if key not in seen or e.confidence > seen[key].confidence:
                seen[key] = e

        new_edges = [e for e in seen.values() if (e.source, e.target) not in committed_pairs]
        print(f"\nNew unique edges proposed: {len(new_edges)}")

        if not new_edges:
            print("Nothing to add.")
            return 0

        if dry_run:
            print("\n[dry-run] Would add:")
            for e in sorted(new_edges, key=lambda x: -x.confidence):
                print(f"  {e.source} → {e.target}  [{e.type}]  conf={e.confidence}  | {e.reason}")
            return 0

        written = self._write_edges(new_edges, committed_pairs)
        print(f"Written {written} new edges to {self.edges_path}")
        return 0
