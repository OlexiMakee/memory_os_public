"""
Link Inferrer — automatic edge discovery for the Memory OS graph.

Two complementary methods:
  text  — offline keyword/ID matching, zero cost, instant
  llm   — LLM batch analysis, finds semantic connections text can't see
  both  — run text first, then LLM on the remaining unlinked nodes (default)
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from memory_os.core.config import MemoryOSConfig
from memory_os.core.logger import get_logger
from memory_os.core.models import MemoryEdge

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# LLM system prompt
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
# Text matching
# ---------------------------------------------------------------------------

def _id_keywords(node_id: str) -> Set[str]:
    """Extract searchable keywords from a node ID like 'notion.shubin' → {'shubin'}."""
    parts = re.split(r"[._\-/]", node_id.lower())
    # Generic words too common to be reliable edge signals
    skip = {
        "notion", "page", "home", "entry", "database", "status", "verified", "fact",
        "book", "books", "film", "films", "game", "games", "idea", "ideas",
        "plan", "wiki", "team", "demo", "refs", "tbd", "real", "base",
        "core", "info", "data", "list", "item", "type", "work", "note",
        "tips", "docs", "tech", "prod", "mark",
    }
    # Require ≥5 chars to avoid matching common 4-letter English words
    return {p for p in parts if len(p) >= 5 and p not in skip}


def _summary_keywords(summary: str) -> Set[str]:
    """Extract lowercase words ≥4 chars from summary, skip common stop words."""
    stop = {
        "this", "that", "with", "from", "have", "will", "been", "into",
        "more", "some", "when", "what", "which", "then", "than", "also",
        "each", "they", "their", "there", "about", "after", "where",
        "other", "used", "uses", "note", "your", "object", "value",
        "these", "those", "param", "field", "list", "type", "data",
    }
    words = re.findall(r"[a-zа-яіїєёa-z]{4,}", summary.lower())
    return {w for w in words if w not in stop}


def _text_score(node_a: dict, node_b: dict) -> float:
    """
    Return a 0-1 score for how likely an edge A→B makes sense.

    Signal: B's ID keywords appear explicitly (whole-word) in A's summary.
    This is a direct-mention test — avoids false positives from shared boilerplate.

    Score = matched_keywords / len(id_kw_b)
    """
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
    """Return candidate edges via keyword/ID text matching."""
    candidates: List[MemoryEdge] = []
    node_index = {n["id"]: n for n in nodes}

    for a in nodes:
        for b in nodes:
            if a["id"] == b["id"]:
                continue
            if (a["id"], b["id"]) in existing_pairs:
                continue
            score = _text_score(a, b)
            if score >= min_score:
                candidates.append(
                    MemoryEdge(
                        source=a["id"],
                        target=b["id"],
                        type="depends_on",
                        confidence=round(score, 2),
                        reason="text-match",
                    )
                )

    # Deduplicate: keep only the higher-score direction for each pair
    seen: Dict[Tuple[str, str], MemoryEdge] = {}
    for e in candidates:
        key = tuple(sorted([e.source, e.target]))
        if key not in seen or e.confidence > seen[key].confidence:
            seen[key] = e

    return list(seen.values())


# ---------------------------------------------------------------------------
# LLM batch inference
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

    # Build compact node list for context
    def _node_line(n: dict) -> str:
        summary = n["summary"][:200].replace("\n", " ")
        return f'{n["id"]}: {summary}'

    # Existing edges as compact set for the prompt
    existing_lines = [f'{s} -> {t}' for s, t in sorted(existing_pairs)[:200]]

    # Split nodes into batches to stay within context limits
    for i in range(0, len(nodes), batch_size):
        batch = nodes[i: i + batch_size]
        node_block = "\n".join(_node_line(n) for n in batch)

        # Include all node IDs as context even for smaller batches
        all_ids = "\n".join(n["id"] for n in nodes)

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

            # Extract JSON array from response
            raw = raw.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)

            proposals = json.loads(raw)
            if not isinstance(proposals, list):
                logger.warning("[LinkInferrer] LLM returned non-list, skipping batch")
                continue

            for p in proposals:
                src = p.get("source", "")
                tgt = p.get("target", "")
                etype = p.get("type", "depends_on")
                reason = p.get("reason", "llm-infer")

                if not src or not tgt or src == tgt:
                    continue
                if (src, tgt) in existing_pairs:
                    continue

                all_edges.append(
                    MemoryEdge(
                        source=src,
                        target=tgt,
                        type=etype,
                        confidence=0.8,
                        reason=reason,
                    )
                )

        except (json.JSONDecodeError, KeyError) as exc:
            logger.error(f"[LinkInferrer] Failed to parse LLM response: {exc}")
        except RuntimeError as exc:
            logger.error(f"[LinkInferrer] LLM call failed: {exc}")
            raise

    return all_edges


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
        method: str = "both",
        dry_run: bool = False,
        min_score: float = 0.3,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        batch_size: int = 60,
    ) -> int:
        nodes = self._load_nodes()
        if not nodes:
            print("No nodes found in memory/nodes.jsonl")
            return 1

        existing_pairs = self._load_existing_pairs()
        print(f"Loaded {len(nodes)} nodes, {len(existing_pairs)} existing edges.")

        all_candidates: List[MemoryEdge] = []

        # ── Text method ──────────────────────────────────────────────────
        if method in ("text", "both"):
            print("Running text matching (looping until exhausted)...")
            pass_num = 1
            while True:
                text_edges = infer_text(nodes, existing_pairs, min_score=min_score)
                if not text_edges:
                    if pass_num == 1:
                        print("  → 0 candidate edges from text matching")
                    break
                print(f"  → Pass {pass_num}: {len(text_edges)} candidate edges from text matching")
                all_candidates.extend(text_edges)
                for e in text_edges:
                    existing_pairs.add((e.source, e.target))
                    existing_pairs.add((e.target, e.source)) # Also prevent reverse duplicates just in case
                pass_num += 1

        # ── LLM method ───────────────────────────────────────────────────
        if method in ("llm", "both"):
            # For 'both': only pass nodes that text didn't fully saturate
            if method == "both":
                # Find nodes that still have few connections after text pass
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
            else:
                llm_nodes = nodes
                print(f"Running LLM inference on all {len(llm_nodes)} nodes...")

            llm_edges = infer_llm(
                llm_nodes, existing_pairs,
                provider=provider, model=model, batch_size=batch_size,
            )
            print(f"  → {len(llm_edges)} candidate edges from LLM")
            all_candidates.extend(llm_edges)

        # ── Deduplicate final candidates ─────────────────────────────────
        seen: Dict[Tuple[str, str], MemoryEdge] = {}
        for e in all_candidates:
            key = (e.source, e.target)
            if key not in seen or e.confidence > seen[key].confidence:
                seen[key] = e

        new_edges = [e for e in seen.values() if (e.source, e.target) not in existing_pairs]
        print(f"\nNew unique edges proposed: {len(new_edges)}")

        if not new_edges:
            print("Nothing to add.")
            return 0

        # ── Dry run ──────────────────────────────────────────────────────
        if dry_run:
            print("\n[dry-run] Would add:")
            for e in sorted(new_edges, key=lambda x: -x.confidence):
                print(f"  {e.source} → {e.target}  [{e.type}]  conf={e.confidence}  | {e.reason}")
            return 0

        # ── Write ────────────────────────────────────────────────────────
        written = self._write_edges(new_edges, existing_pairs)
        print(f"Written {written} new edges to {self.edges_path}")
        return 0
