"""
Tests for Memory OS graph memory — dedup, access tracking, semantic search,
background link-infer locking, GraphMapper cluster nodes, and node decay.

Run with:
    PYTHONPATH=src python -m pytest tests/test_graph_memory.py -v
"""
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from memory_os.core.config import MemoryOSConfig
from memory_os.agent_brain.types import ActionRequest
from memory_os.agent_brain.executors import (
    memory_write_executor,
    _background_link_infer,
    _link_infer_lock,
)
from memory_os.modules.search import MemorySearcher, VERBATIM_QUERY_SCORE
from memory_os.modules.lifecycle import LifecycleManager, PROMOTABLE_NODE_TYPES
from memory_os.toolkit.graph_mapper import GraphMapper
from memory_os.toolkit.link_inferrer import (
    infer_bm25,
    infer_tags,
    infer_text,
    _infer_edge_type,
    _inventory_node_role,
    _is_low_value_inventory_cooccurrence,
    _limit_edges_by_degree,
    _is_linkable_node,
)
from memory_os.core.models import MemoryEdge
from memory_os.core.repository import MemoryRepository
from memory_os.core.storage import FileSystemMemoryStorage
from memory_os.core.core import MemoryOS
from memory_os.modules.validator import VALID_EDGE_TYPES

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _write_jsonl(path: Path, nodes: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for n in nodes:
            f.write(json.dumps(n) + "\n")


@pytest.fixture
def root(tmp_path):
    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    return tmp_path


def _cfg(root: Path) -> MemoryOSConfig:
    return MemoryOSConfig(config_path=str(root / "memory_os.config.json"))


def test_repository_exposes_only_patch_backed_graph_mutations(root):
    repository = MemoryRepository(FileSystemMemoryStorage(), _cfg(root))

    for method in (
        "add_node",
        "save_nodes",
        "add_edge",
        "save_edges",
        "_add_node",
        "_save_nodes",
        "_add_edge",
        "_save_edges",
    ):
        assert not hasattr(repository, method)


def test_optimize_db_does_not_issue_wal_checkpoint():
    statements = []

    class RecordingConnection:
        def execute(self, statement):
            statements.append(statement)
            return self

        def commit(self):
            return None

        def close(self):
            return None

    memory = object.__new__(MemoryOS)
    memory.get_connection = lambda: RecordingConnection()

    memory.optimize_db()

    assert not any("wal_checkpoint" in statement.lower() for statement in statements)


# ---------------------------------------------------------------------------
# Test 1: dedup — same summary, non-stale node → status="deduped"
# ---------------------------------------------------------------------------

def test_memory_write_dedup(root):
    config = _cfg(root)
    summary = "the project uses python 3.11 and pytest for unit testing"

    existing = {
        "id": "fact:existing-001",
        "type": "fact",
        "summary": summary,
        "evidence": [],
        "status": "verified",
        "freshness": datetime.now().isoformat(timespec="seconds"),
        "trust": "verified",
        "related_nodes": [],
        "tags": [],
    }
    _write_jsonl(config.memory_dir / "nodes.jsonl", [existing])

    executor = memory_write_executor(config)
    request = ActionRequest(action="memory.write", args={"summary": summary, "type": "fact"})

    result = executor(request)

    assert result.ok is True
    assert result.data["status"] == "deduped"
    assert result.data["node_id"] == existing["id"]

    # No second node should be written
    lines = [l for l in (config.memory_dir / "nodes.jsonl").read_text().splitlines() if l.strip()]
    assert len(lines) == 1, "Dedup must not append a second node"


# ---------------------------------------------------------------------------
# Test 2: dedup skips stale nodes → new draft node is written
# ---------------------------------------------------------------------------

def test_memory_write_dedup_skips_stale(root):
    config = _cfg(root)
    summary = "the project uses python 3.11 and pytest for unit testing"

    stale_node = {
        "id": "fact:stale-001",
        "type": "fact",
        "summary": summary,
        "evidence": [],
        "status": "stale",
        "freshness": datetime.now().isoformat(timespec="seconds"),
        "trust": "unverified",
        "related_nodes": [],
        "tags": [],
    }
    _write_jsonl(config.memory_dir / "nodes.jsonl", [stale_node])

    executor = memory_write_executor(config)
    request = ActionRequest(action="memory.write", args={"summary": summary, "type": "fact"})

    # Suppress background link-infer daemon thread so the test stays clean
    with patch("memory_os.agent_brain.executors._background_link_infer"):
        result = executor(request)

    assert result.ok is True
    assert result.data.get("status") != "deduped", "Stale node must not trigger dedup"

    lines = [l for l in (config.memory_dir / "nodes.jsonl").read_text().splitlines() if l.strip()]
    assert len(lines) == 2, "A new draft node should have been appended alongside the stale one"


@pytest.mark.parametrize(
    ("score", "expected_status"),
    [
        (VERBATIM_QUERY_SCORE - 0.001, "draft"),
        (VERBATIM_QUERY_SCORE, "deduped"),
    ],
)
def test_memory_write_dedup_uses_shared_verbatim_score(root, score, expected_status):
    config = _cfg(root)
    match = {
        "id": "fact:score-boundary",
        "type": "fact",
        "summary": "shared score boundary",
        "status": "verified",
        "search_score": score,
    }
    with patch.object(MemorySearcher, "search_memory", return_value=[match]), patch.object(
        LifecycleManager, "propose", return_value=0
    ), patch("memory_os.agent_brain.executors._background_link_infer"):
        result = memory_write_executor(config)(ActionRequest(
            action="memory.write",
            args={"summary": "shared score boundary", "type": "fact"},
        ))

    assert result.data["status"] == expected_status


# ---------------------------------------------------------------------------
# Test 3: access tracking writes node_stats.json after a search hit
# ---------------------------------------------------------------------------

def test_access_tracking_writes_node_stats(root):
    config = _cfg(root)
    summary = "access-tracking-test unique phrase zxqv7f8x9"
    node_id = "fact:access-track-001"

    node = {
        "id": node_id,
        "type": "fact",
        "summary": summary,
        "evidence": [],
        "status": "verified",
        "freshness": datetime.now().isoformat(timespec="seconds"),
        "trust": "verified",
        "related_nodes": [],
        "tags": [],
    }
    _write_jsonl(config.memory_dir / "nodes.jsonl", [node])

    searcher = MemorySearcher(config)
    searcher.search_memory(summary)

    stats_path = config.memory_dir / "node_stats.json"
    assert stats_path.exists(), "node_stats.json should have been created by search"

    stats = json.loads(stats_path.read_text("utf-8"))
    assert node_id in stats, f"{node_id} must appear in node_stats.json"
    assert stats[node_id]["count"] >= 1
    assert stats[node_id]["last_accessed"] != ""


def test_search_access_stats_prevent_lifecycle_decay(root):
    config = _cfg(root)
    old_ts = (datetime.now(UTC) - timedelta(days=90)).isoformat()
    node = {
        "id": "fact:accessed-old-001",
        "type": "fact",
        "summary": "old durable knowledge accessed immediately before decay",
        "evidence": [],
        "status": "verified",
        "freshness": old_ts,
        "valid_from": old_ts,
        "trust": "verified",
        "related_nodes": [],
        "tags": [],
    }
    _write_jsonl(config.memory_dir / "nodes.jsonl", [node])
    MemorySearcher(config).search_memory(node["summary"])

    assert LifecycleManager(config).decay_nodes(days_stale=30) == 0


def test_promotable_node_types_are_immutable_and_include_module_clusters():
    assert isinstance(PROMOTABLE_NODE_TYPES, frozenset)
    assert "module_cluster" in PROMOTABLE_NODE_TYPES


# ---------------------------------------------------------------------------
# Test 4: semantic search fallback via cosine similarity
# ---------------------------------------------------------------------------

def test_semantic_search_fallback_cosine(root):
    config = _cfg(root)

    # A node whose summary shares NO tokens with the queries below.
    # Use a single camelCase-free, hyphen-free token so the tokenizer produces
    # exactly one token that doesn't collide with either query.
    node_id = "test-node-1"
    node = {
        "id": node_id,
        "type": "fact",
        "summary": "zzz7v8q9unique",   # single token, no overlap with queries
        "evidence": [],
        "status": "verified",
        "freshness": datetime.now().isoformat(timespec="seconds"),
        "trust": "verified",
        "related_nodes": [],
        "tags": [],
    }
    _write_jsonl(config.memory_dir / "nodes.jsonl", [node])

    # EmbeddingProvider._load_cache() reads entry["vector"] (not "vec")
    embed_path = config.memory_dir / "embeddings.jsonl"
    embed_path.write_text(
        json.dumps({"id": node_id, "vector": [1.0, 0.0, 0.0]}) + "\n",
        encoding="utf-8",
    )

    # Queries are chosen to share NO tokens with "zzz7v8q9unique" or "test-node-1".
    # Tokens of query_a/b: {"qqq7v8opaque9query1a"/"1b"} — zero overlap with node.
    QUERY_MATCH    = "qqq7v8opaque9query1a"
    QUERY_NO_MATCH = "qqq7v8opaque9query1b"

    # Matching case: cosine(q, node) = 1.0 exceeds the configured default.
    searcher = MemorySearcher(config)
    with patch(
        "memory_os.toolkit.embedding_provider.EmbeddingProvider._embed",
        return_value=[1.0, 0.0, 0.0],
    ):
        results = searcher.search_memory(QUERY_MATCH)

    ids = [r["id"] for r in results]
    assert node_id in ids, "Cosine-similar node must appear in semantic fallback results"

    # Non-matching case: cosine(q, node) = 0.0 is below the configured default.
    # Different query string → different cache key, guaranteed cache miss.
    with patch(
        "memory_os.toolkit.embedding_provider.EmbeddingProvider._embed",
        return_value=[0.0, 1.0, 0.0],
    ):
        results_no = searcher.search_memory(QUERY_NO_MATCH)

    ids_no = [r["id"] for r in results_no]
    assert node_id not in ids_no, "Orthogonal vector (cosine=0.0) must not appear in results"


@pytest.mark.parametrize("semantic", [False, True])
def test_semantic_search_uses_configured_similarity_threshold(root, semantic):
    config_path = root / "memory_os.config.json"
    config_path.write_text(
        json.dumps({
            "version": "0.1",
            "memory": {
                "semantic_similarity_threshold": 0.8,
                "semantic_fallback_threshold": 0.8,
            },
        }),
        encoding="utf-8",
    )
    config = _cfg(root)
    node_id = "fact:semantic-threshold"
    _write_jsonl(config.memory_dir / "nodes.jsonl", [{
        "id": node_id,
        "type": "fact",
        "summary": "zzzxxyy",
        "status": "verified",
        "confidence": 1.0,
    }])
    (config.memory_dir / "embeddings.jsonl").write_text(
        json.dumps({"id": node_id, "vector": [1.0, 0.0]}) + "\n",
        encoding="utf-8",
    )

    searcher = MemorySearcher(config)
    with patch(
        "memory_os.toolkit.embedding_provider.EmbeddingProvider._embed",
        return_value=[0.7, 0.714142842854285],
    ), patch(
        "memory_os.toolkit.embedding_provider.EmbeddingProvider.embed_nodes",
        return_value={node_id: [1.0, 0.0]},
    ):
        results = searcher.search_memory("qqqopaque", semantic=semantic)

    assert node_id not in {result["id"] for result in results}


# ---------------------------------------------------------------------------
# Test 5: _background_link_infer lock prevents concurrent execution
# ---------------------------------------------------------------------------

def test_background_link_infer_lock(root):
    config = _cfg(root)
    call_count = []

    def fake_run(*args, **kwargs):
        call_count.append(1)

    with patch("memory_os.toolkit.link_inferrer.LinkInferrer") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.run.side_effect = fake_run
        mock_cls.return_value = mock_instance

        # Simulate "already running" by holding the lock externally.
        _link_infer_lock.acquire()
        try:
            _background_link_infer(config)  # should skip: cannot acquire
        finally:
            _link_infer_lock.release()

        assert len(call_count) == 0, "LinkInferrer.run must not be called while lock is held"

        # Lock is now free — this call should run normally.
        _background_link_infer(config)

    assert len(call_count) == 1, "LinkInferrer.run should have been called exactly once"


# ---------------------------------------------------------------------------
# Test 6: GraphMapper emits module_cluster nodes and contains edges
# ---------------------------------------------------------------------------

def test_graph_mapper_emits_cluster_nodes(root):
    config = _cfg(root)

    # Minimal snapshot with 2 files in the same top-level directory ("src").
    snapshot = {
        "generated_at": "2026-06-28T00:00:00Z",
        "items": [
            {
                "meta": {
                    "file": "src/alpha.py",
                    "dependencies": [],
                    "layer": "app",
                    "classes": [],
                    "functions": ["alpha_fn"],
                    "routes": [],
                },
                "vector_text": "alpha module",
            },
            {
                "meta": {
                    "file": "src/beta.py",
                    "dependencies": [],
                    "layer": "app",
                    "classes": [],
                    "functions": ["beta_fn"],
                    "routes": [],
                },
                "vector_text": "beta module",
            },
        ],
    }
    snapshot_path = config.snapshot_file
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    # Pre-existing memory node whose evidence overlaps with the cluster files.
    existing_mem_node = {
        "id": "fact:mem-overlap-001",
        "type": "fact",
        "summary": "alpha module contains important logic",
        "evidence": ["src/alpha.py"],
        "status": "verified",
        "freshness": datetime.now().isoformat(timespec="seconds"),
        "trust": "verified",
        "related_nodes": [],
        "tags": [],
    }
    _write_jsonl(config.memory_dir / "nodes.jsonl", [existing_mem_node])

    # Suppress the background link-infer daemon thread to keep the test fast.
    with patch("memory_os.agent_brain.executors._background_link_infer"):
        result = GraphMapper(config).run(emit_nodes=True)

    assert result["status"] == "success", f"GraphMapper.run failed: {result}"

    # nodes.jsonl must contain at least one module_cluster node for the "src" dir.
    raw_nodes = [
        json.loads(l)
        for l in (config.memory_dir / "nodes.jsonl").read_text().splitlines()
        if l.strip()
    ]
    cluster_nodes = [n for n in raw_nodes if n.get("type") == "module_cluster"]
    assert cluster_nodes, "Should have emitted at least one module_cluster node"
    cluster_ids = {n["id"] for n in cluster_nodes}
    assert any("src" in cid for cid in cluster_ids), \
        f"Expected a cluster node for 'src' directory, got: {cluster_ids}"

    # edges.jsonl must contain a 'contains' edge pointing to the overlapping memory node.
    edges_path = config.memory_dir / "edges.jsonl"
    assert edges_path.exists(), "edges.jsonl must have been created by GraphMapper"
    raw_edges = [
        json.loads(l)
        for l in edges_path.read_text().splitlines()
        if l.strip()
    ]
    contains_edges = [e for e in raw_edges if e.get("type") == "contains"]
    assert contains_edges, "Should have emitted at least one 'contains' edge"
    targets = {e["target"] for e in contains_edges}
    assert "fact:mem-overlap-001" in targets, \
        f"Expected a 'contains' edge to 'fact:mem-overlap-001', got targets: {targets}"


# ---------------------------------------------------------------------------
# Test 7: decay_nodes archives old unaccessed nodes, spares recent ones
# ---------------------------------------------------------------------------

def test_decay_nodes_archives_old_unaccessed(root):
    config = _cfg(root)

    old_ts = (datetime.now(UTC) - timedelta(days=60)).isoformat(timespec="seconds").replace("+00:00", "Z")
    now_ts = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    old_node = {
        "id": "fact:old-stale-001",
        "type": "fact",
        "summary": "this node is very old and was never accessed",
        "evidence": [],
        "status": "verified",
        "freshness": old_ts,
        "valid_from": old_ts,
        "trust": "verified",
        "related_nodes": [],
        "tags": [],
    }
    recent_node = {
        "id": "fact:recent-001",
        "type": "fact",
        "summary": "this node is fresh and must be kept",
        "evidence": [],
        "status": "verified",
        "freshness": now_ts,
        "valid_from": now_ts,
        "trust": "verified",
        "related_nodes": [],
        "tags": [],
    }
    pinned_node = {
        "id": "fact:pinned-old-001",
        "type": "fact",
        "summary": "this old node is pinned and must be kept",
        "evidence": [],
        "status": "verified",
        "freshness": old_ts,
        "valid_from": old_ts,
        "trust": "verified",
        "related_nodes": [],
        "tags": ["pinned"],
    }
    _write_jsonl(config.memory_dir / "nodes.jsonl", [old_node, recent_node, pinned_node])
    # No node_stats.json → no recorded last_accessed for either node.

    propose_calls: list = []
    apply_calls: list = []

    def fake_propose(patch):
        propose_calls.append(patch.source)
        return patch.id

    def fake_apply(patch_id):
        apply_calls.append(patch_id)
        return True

    with patch("memory_os.core.patch.RelationPatchStore.propose", side_effect=fake_propose), \
         patch("memory_os.core.patch.RelationPatchStore.apply", side_effect=fake_apply):
        lifecycle = LifecycleManager(config)
        count = lifecycle.decay_nodes(days_stale=30)

    assert count == 1, f"Expected exactly 1 archived node, got {count}"
    assert old_node["id"] in propose_calls, \
        f"Old node '{old_node['id']}' must have had a deprecation patch proposed"
    assert len(apply_calls) == 1, \
        f"apply() should have been called exactly once, got {len(apply_calls)}"
    # Recent node must not be touched.
    assert recent_node["id"] not in propose_calls, \
        "Recent node must not be included in decay"
    assert pinned_node["id"] not in propose_calls, \
        "Pinned node must not be included in decay"


def test_lifecycle_transition_preserves_patch_audit_event(root):
    config = _cfg(root)
    evidence = root / "README.md"
    evidence.write_text("evidence\n", encoding="utf-8")

    node = {
        "id": "fact:lifecycle-audit-001",
        "type": "fact",
        "summary": "lifecycle transition preserves patch audit events",
        "evidence": ["README.md"],
        "status": "draft",
        "freshness": datetime.now().isoformat(timespec="seconds"),
        "trust": "unverified",
        "related_nodes": [],
        "tags": [],
    }
    proposed_event = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "event": "memory.node.proposed",
        "node_id": node["id"],
        "claim": "Propose lifecycle audit test",
        "evidence": ["README.md"],
        "validator": "test",
        "status": "pending",
    }
    _write_jsonl(config.memory_dir / "nodes.jsonl", [node])
    _write_jsonl(config.memory_dir / "edges.jsonl", [])
    _write_jsonl(config.memory_dir / "events.jsonl", [proposed_event])

    lifecycle = LifecycleManager(config)
    assert lifecycle.transition(validator="test") == 0

    events = [json.loads(line) for line in (config.memory_dir / "events.jsonl").read_text().splitlines()]

    assert any(
        event.get("event") == "memory.patch.replace_nodes"
        and event.get("validator") == "relation_patch_store"
        for event in events
    )
    assert any(
        event.get("event") == "memory.node.proposed"
        and event.get("node_id") == node["id"]
        and event.get("status") == "accepted"
        for event in events
    )
    assert any(
        event.get("event") == "memory.node.verified"
        and event.get("node_id") == node["id"]
        for event in events
    )


def test_lifecycle_transition_confidence_eval_gate(root):
    config = _cfg(root)
    (root / "README.md").write_text("test evidence file", encoding="utf-8")
    low_conf_node = {
        "id": "fact:low-conf-001",
        "type": "fact",
        "summary": "node with low confidence score below threshold",
        "evidence": ["README.md"],
        "status": "draft",
        "confidence": 0.3,
    }
    high_conf_node = {
        "id": "fact:high-conf-001",
        "type": "fact",
        "summary": "node with high confidence score above threshold",
        "evidence": ["README.md"],
        "status": "draft",
        "confidence": 0.9,
    }
    _write_jsonl(config.memory_dir / "nodes.jsonl", [low_conf_node, high_conf_node])
    _write_jsonl(config.memory_dir / "edges.jsonl", [])
    _write_jsonl(config.memory_dir / "events.jsonl", [])

    lifecycle = LifecycleManager(config)
    lifecycle.transition(validator="test", min_confidence=0.7)

    nodes = [json.loads(line) for line in (config.memory_dir / "nodes.jsonl").read_text().splitlines()]
    nodes_by_id = {n["id"]: n for n in nodes}

    # low confidence HOLDS the candidate in draft (retryable), it is not staled
    assert nodes_by_id["fact:low-conf-001"]["status"] == "draft"
    assert nodes_by_id["fact:high-conf-001"]["status"] == "verified"
    events = [json.loads(line) for line in (config.memory_dir / "events.jsonl").read_text().splitlines()]
    assert not any(
        event.get("event") == "memory.node.rejected"
        and event.get("node_id") == "fact:low-conf-001"
        for event in events
    )


def test_lifecycle_transition_uses_config_confidence_threshold(root):
    (root / "memory_os.config.json").write_text(
        json.dumps({"version": "0.1", "memory": {"confidence_threshold": 0.8}}),
        encoding="utf-8",
    )
    config = _cfg(root)
    (root / "README.md").write_text("test evidence file", encoding="utf-8")
    _write_jsonl(
        config.memory_dir / "nodes.jsonl",
        [
            {
                "id": "fact:conf-079",
                "type": "fact",
                "summary": "below configured threshold",
                "evidence": ["README.md"],
                "status": "draft",
                "confidence": 0.79,
            },
            {
                "id": "fact:conf-080",
                "type": "fact",
                "summary": "at configured threshold",
                "evidence": ["README.md"],
                "status": "draft",
                "confidence": 0.8,
            },
        ],
    )
    _write_jsonl(config.memory_dir / "edges.jsonl", [])
    _write_jsonl(config.memory_dir / "events.jsonl", [])

    lifecycle = LifecycleManager(config)
    lifecycle.transition(validator="test")

    nodes = {json.loads(line)["id"]: json.loads(line) for line in (config.memory_dir / "nodes.jsonl").read_text().splitlines()}
    assert nodes["fact:conf-079"]["status"] == "draft"
    assert nodes["fact:conf-080"]["status"] == "verified"


def test_lifecycle_candidate_promote_reject_cycle(root):
    config = _cfg(root)
    (root / "README.md").write_text("test evidence file", encoding="utf-8")
    lifecycle = LifecycleManager(config)

    assert lifecycle.propose_candidate(
        node_id="fact:candidate-low",
        node_type="fact",
        summary="low confidence candidate can be explicitly promoted",
        evidence=["README.md"],
        confidence=0.2,
        validator="test",
    ) == 0
    assert lifecycle.propose_candidate(
        node_id="fact:candidate-reject",
        node_type="fact",
        summary="candidate rejected after eval",
        evidence=["README.md"],
        confidence=0.95,
        validator="test",
    ) == 0

    assert lifecycle.promote("fact:candidate-low", validator="test") == 0
    assert lifecycle.reject("fact:candidate-reject", reason="eval failed", validator="test") == 0

    nodes = {json.loads(line)["id"]: json.loads(line) for line in (config.memory_dir / "nodes.jsonl").read_text().splitlines()}
    assert nodes["fact:candidate-low"]["status"] == "verified"
    assert nodes["fact:candidate-low"]["confidence"] == 0.2
    assert nodes["fact:candidate-reject"]["status"] == "stale"

    events = [json.loads(line) for line in (config.memory_dir / "events.jsonl").read_text().splitlines()]
    assert any(event.get("event") == "memory.node.verified" and event.get("promotion_mode") == "explicit" for event in events)
    assert any(event.get("event") == "memory.node.rejected" and event.get("node_id") == "fact:candidate-reject" for event in events)


def test_lifecycle_mutations_use_relation_patch_store_not_repository_facades(root, monkeypatch):
    config = _cfg(root)
    (root / "README.md").write_text("test evidence file", encoding="utf-8")

    def fail_upsert(*_args, **_kwargs):
        raise AssertionError("LifecycleManager must not call MemoryRepository.upsert_node")

    def fail_replace(*_args, **_kwargs):
        raise AssertionError("LifecycleManager must not call MemoryRepository.replace_nodes")

    monkeypatch.setattr(MemoryRepository, "upsert_node", fail_upsert)
    monkeypatch.setattr(MemoryRepository, "replace_nodes", fail_replace)

    lifecycle = LifecycleManager(config)
    assert lifecycle.propose(
        node_id="fact:patch-route-transition",
        node_type="fact",
        summary="transition mutation goes through relation patches",
        evidence="README.md",
        confidence=0.95,
    ) == 0
    assert lifecycle.transition(validator="test", min_confidence=0.7) == 0

    assert lifecycle.propose_candidate(
        node_id="fact:patch-route-promote",
        node_type="fact",
        summary="explicit promote mutation goes through relation patches",
        evidence=["README.md"],
        confidence=0.2,
        validator="test",
    ) == 0
    assert lifecycle.promote("fact:patch-route-promote", validator="test") == 0

    assert lifecycle.propose_candidate(
        node_id="fact:patch-route-reject",
        node_type="fact",
        summary="explicit reject mutation goes through relation patches",
        evidence=["README.md"],
        confidence=0.9,
        validator="test",
    ) == 0
    assert lifecycle.reject("fact:patch-route-reject", reason="eval failed", validator="test") == 0

    nodes = {json.loads(line)["id"]: json.loads(line) for line in (config.memory_dir / "nodes.jsonl").read_text().splitlines()}
    assert nodes["fact:patch-route-transition"]["status"] == "verified"
    assert nodes["fact:patch-route-promote"]["status"] == "verified"
    assert nodes["fact:patch-route-reject"]["status"] == "stale"


def test_lifecycle_prune_uses_single_sqlite_sync(root, monkeypatch):
    config = _cfg(root)
    active = {
        "id": "fact:active-001",
        "type": "fact",
        "summary": "active node",
        "evidence": [],
        "status": "verified",
        "freshness": datetime.now().isoformat(timespec="seconds"),
        "trust": "verified",
        "related_nodes": [],
        "tags": [],
    }
    stale = {
        "id": "fact:stale-001",
        "type": "fact",
        "summary": "stale node",
        "evidence": [],
        "status": "stale",
        "freshness": datetime.now().isoformat(timespec="seconds"),
        "trust": "verified",
        "related_nodes": [],
        "tags": [],
    }
    _write_jsonl(config.memory_dir / "nodes.jsonl", [active, stale])
    _write_jsonl(
        config.memory_dir / "edges.jsonl",
        [
            {"source": "fact:active-001", "target": "fact:active-001", "type": "depends_on"},
            {"source": "fact:active-001", "target": "fact:missing-001", "type": "depends_on"},
            {"source": "fact:active-001", "target": "fact:stale-001", "type": "depends_on"},
        ],
    )

    sync_calls = []
    monkeypatch.setattr("memory_os.modules.search.MemorySearcher.incremental_sync", lambda self, patch: sync_calls.append(patch))

    lifecycle = LifecycleManager(config)
    assert lifecycle.prune() == 0

    assert len(sync_calls) == 2
    nodes = [json.loads(line) for line in (config.memory_dir / "nodes.jsonl").read_text().splitlines()]
    edges = [json.loads(line) for line in (config.memory_dir / "edges.jsonl").read_text().splitlines()]
    assert [n["id"] for n in nodes] == ["fact:active-001"]
    assert edges == []
    archived_nodes = [json.loads(line) for line in (config.memory_dir / "archived_nodes.jsonl").read_text().splitlines()]
    archived_edges = [json.loads(line) for line in (config.memory_dir / "archived_edges.jsonl").read_text().splitlines()]
    assert archived_nodes[0]["id"] == "fact:stale-001"
    assert len(archived_edges) == 2


def test_lifecycle_prune_skips_pinned_stale_nodes(root, monkeypatch):
    """A stale/superseded node tagged 'pinned' must survive prune, mirroring decay_nodes's pin-guard.

    Regression: prune() previously archived any stale/superseded node regardless of the
    'pinned' tag, silently deleting curated architecture/strategy facts whenever a
    transition mislabeled them (found live: arch:memory-os-core-layout,
    strategy:consensus-2026-2027, arch:agent-registry, strategy:open-items-20260701 all
    vanished this way despite being pinned).
    """
    config = _cfg(root)
    pinned_stale = {
        "id": "fact:pinned-stale-001",
        "type": "fact",
        "summary": "pinned but stale node",
        "evidence": [],
        "status": "stale",
        "freshness": datetime.now().isoformat(timespec="seconds"),
        "trust": "verified",
        "related_nodes": [],
        "tags": ["pinned"],
    }
    unpinned_stale = {
        "id": "fact:unpinned-stale-001",
        "type": "fact",
        "summary": "unpinned stale node",
        "evidence": [],
        "status": "stale",
        "freshness": datetime.now().isoformat(timespec="seconds"),
        "trust": "verified",
        "related_nodes": [],
        "tags": [],
    }
    _write_jsonl(config.memory_dir / "nodes.jsonl", [pinned_stale, unpinned_stale])
    _write_jsonl(config.memory_dir / "edges.jsonl", [])

    monkeypatch.setattr("memory_os.modules.search.MemorySearcher.incremental_sync", lambda self, patch: None)

    lifecycle = LifecycleManager(config)
    assert lifecycle.prune() == 0

    nodes = [json.loads(line) for line in (config.memory_dir / "nodes.jsonl").read_text().splitlines()]
    assert [n["id"] for n in nodes] == ["fact:pinned-stale-001"]
    archived_nodes = [json.loads(line) for line in (config.memory_dir / "archived_nodes.jsonl").read_text().splitlines()]
    assert [n["id"] for n in archived_nodes] == ["fact:unpinned-stale-001"]


def test_link_infer_ignores_generic_agent_comm_tags(root):
    nodes = [
        {"id": f"comm:task-{idx}", "summary": f"message {idx}", "tags": ["agent_comm", "codex", "status_report"]}
        for idx in range(8)
    ]

    assert infer_tags(nodes, set()) == []


def test_validator_allows_link_infer_edge_types(root):
    assert "co_tagged" in VALID_EDGE_TYPES
    assert "co_created" in VALID_EDGE_TYPES


def test_link_infer_skips_agent_comm_nodes(root):
    assert _is_linkable_node({"id": "fact:real", "tags": ["strategy"]}) is True
    assert _is_linkable_node({"id": "comm:task-1", "tags": ["strategy"]}) is False
    assert _is_linkable_node({"id": "fact:comm", "tags": ["agent_comm"]}) is False
    assert _is_linkable_node({"id": "fact:comm", "domain": "agent_comm"}) is False


def test_link_infer_filters_inventory_cooccurrence_depends_on(root):
    systemd_a = {
        "id": "service:systemd:user:dirmngr.service",
        "type": "fact",
        "summary": "User service `dirmngr.service`: loaded active running",
        "tags": ["linux_inventory", "systemd", "service", "user"],
    }
    systemd_b = {
        "id": "service:systemd:user:gpg-agent.service",
        "type": "fact",
        "summary": "User service `gpg-agent.service`: loaded active running",
        "tags": ["linux_inventory", "systemd", "service", "user"],
    }
    port = {
        "id": "port:127.0.0.1:11434",
        "type": "fact",
        "summary": "Listening port tcp 127.0.0.1:11434 active running",
        "tags": ["linux_inventory", "port"],
    }
    fact = {
        "id": "fact:daemon-health",
        "type": "fact",
        "summary": "daemon health uses active running service state",
        "tags": ["runtime"],
    }

    assert _inventory_node_role(systemd_a) == "systemd_service"
    assert _inventory_node_role(port) == "port"
    assert _is_low_value_inventory_cooccurrence("depends_on", systemd_a, systemd_b, "bm25:12.0")
    assert not _is_low_value_inventory_cooccurrence("triggers", systemd_a, systemd_b, "bm25:12.0")

    bm25_edges = infer_bm25([systemd_a, systemd_b, fact], set(), top_k=5, min_score=0.1)
    assert not any({edge.source, edge.target} == {systemd_a["id"], systemd_b["id"]} for edge in bm25_edges)
    assert any(fact["id"] in {edge.source, edge.target} for edge in bm25_edges)

    text_edges = infer_text([systemd_a, systemd_b, port], set(), min_score=0.1)
    assert text_edges == []


def test_link_infer_degree_cap_limits_dense_candidates(root):
    edges = [
        MemoryEdge(source="hub", target=f"leaf-{idx}", type="depends_on", confidence=0.9)
        for idx in range(20)
    ]

    limited = _limit_edges_by_degree(edges, max_edges_per_node=3)

    assert len(limited) == 3
    assert all(edge.source == "hub" for edge in limited)


def test_sync_graph_nodes_rebuilds_sqlite_without_stale_rows(root):
    config = _cfg(root)
    first = {
        "id": "fact:sync-a",
        "type": "fact",
        "summary": "first sync node",
        "evidence": [],
        "status": "verified",
        "freshness": "2026-07-01T00:00:00",
        "trust": "verified",
        "related_nodes": [],
        "tags": [],
    }
    second = {**first, "id": "fact:sync-b", "summary": "second sync node"}
    _write_jsonl(config.memory_dir / "nodes.jsonl", [first, second])

    repo = MemoryRepository(FileSystemMemoryStorage(), config, indexer=MemoryOS(config))
    repo.sync_graph_nodes()
    _write_jsonl(config.memory_dir / "nodes.jsonl", [second])
    repo.sync_graph_nodes()

    conn = MemoryOS(config).get_connection()
    try:
        rows = conn.execute("SELECT id FROM graph_nodes ORDER BY id").fetchall()
    finally:
        conn.close()

    assert [row["id"] for row in rows] == ["fact:sync-b"]


def test_sync_graph_nodes_reuses_injected_indexer_instead_of_reinstantiating(root):
    """Regression: sync_graph_nodes/sync_graph_edges used to construct a fresh
    MemoryOS(self.config) on every call (re-running init_db()'s schema-creation
    side effect each time) instead of reusing an already-injected indexer.
    """
    config = _cfg(root)
    _write_jsonl(config.memory_dir / "nodes.jsonl", [])
    _write_jsonl(config.memory_dir / "edges.jsonl", [])

    indexer = MemoryOS(config)
    repo = MemoryRepository(FileSystemMemoryStorage(), config, indexer=indexer)

    repo.sync_graph_nodes()
    repo.sync_graph_edges()

    assert repo.indexer is indexer


def test_sync_graph_nodes_lazily_creates_and_caches_indexer_when_absent(root):
    config = _cfg(root)
    _write_jsonl(config.memory_dir / "nodes.jsonl", [])
    _write_jsonl(config.memory_dir / "edges.jsonl", [])

    repo = MemoryRepository(FileSystemMemoryStorage(), config)
    assert repo.indexer is None

    repo.sync_graph_nodes()
    created = repo.indexer
    assert created is not None

    repo.sync_graph_edges()
    assert repo.indexer is created


def test_incremental_stale_index_repair(root, monkeypatch):
    from memory_os.core.patch import RelationPatchStore
    from memory_os.modules.search import MemorySearcher
    from memory_os.toolkit.embedding_provider import EmbeddingProvider

    config = _cfg(root)
    node1 = {
        "id": "fact:node-1",
        "type": "fact",
        "summary": "original node one summary",
        "evidence": [],
        "status": "verified",
        "freshness": "2026-07-01T00:00:00",
        "trust": "verified",
        "related_nodes": [],
        "tags": ["tag1"],
    }
    _write_jsonl(config.memory_dir / "nodes.jsonl", [node1])

    repo = MemoryRepository(FileSystemMemoryStorage(), config, indexer=MemoryOS(config))
    repo.sync_sqlite()

    provider = EmbeddingProvider(config=config)
    provider._append_to_cache("fact:node-1", [0.1] * 768)
    provider._append_to_cache("fact:node-2", [0.2] * 768)

    sync_calls = []
    monkeypatch.setattr(MemoryRepository, "sync_sqlite", lambda self: sync_calls.append(1))

    # 1. Test upsert new node
    node2_patch = repo._make_patch(
        operation="upsert_node",
        target="fact:node-2",
        patch_type="fact",
        payload={
            "node": {
                "id": "fact:node-2",
                "type": "fact",
                "summary": "node two summary",
                "status": "verified",
                "tags": ["tag2"],
            }
        },
        reason="upsert node 2",
    )
    store = RelationPatchStore(repo)
    patch_id = store.propose(node2_patch)
    applied = store.apply(patch_id)
    assert applied is True
    assert len(sync_calls) == 0

    searcher = MemorySearcher(config, repository=repo)
    res = searcher.search_memory("two summary")
    assert any(n.get("id") == "fact:node-2" for n in res)

    # 2. Test update node summary (and check embedding invalidation)
    node1_patch = repo._make_patch(
        operation="update_node",
        target="fact:node-1",
        patch_type="fact",
        payload={"updates": {"summary": "updated node one summary"}},
        reason="update node 1",
    )
    patch_id_2 = store.propose(node1_patch)
    applied = store.apply(patch_id_2)
    assert applied is True
    assert len(sync_calls) == 0

    # Verify FTS/SQLite updated directly in DB
    conn = MemoryOS(config).get_connection()
    try:
        row = conn.execute("SELECT summary FROM graph_nodes WHERE id = ?", ("fact:node-1",)).fetchone()
        assert row["summary"] == "updated node one summary"
    finally:
        conn.close()

    res = searcher.search_memory("updated node one")
    assert any(n.get("id") == "fact:node-1" for n in res)

    cache = provider._load_cache()
    assert "fact:node-1" not in cache
    assert "fact:node-2" in cache

    # 3. Test delete/replace nodes
    remaining_nodes = [n for n in repo.get_nodes() if n.id != "fact:node-2"]
    delete_patch = repo._make_patch(
        operation="replace_nodes",
        target="memory/nodes.jsonl",
        payload={"nodes": [n.to_dict() for n in remaining_nodes]},
        reason="delete node 2",
    )
    patch_id_3 = store.propose(delete_patch)
    applied = store.apply(patch_id_3)
    assert applied is True

    # Verify FTS/SQLite deleted directly in DB
    conn = MemoryOS(config).get_connection()
    try:
        row = conn.execute("SELECT id FROM graph_nodes WHERE id = ?", ("fact:node-2",)).fetchone()
        assert row is None
    finally:
        conn.close()

    cache = provider._load_cache()
    assert "fact:node-2" not in cache


def test_embedding_provider_llama_server_parsing(root):
    from unittest.mock import patch, MagicMock
    from memory_os.toolkit.embedding_provider import EmbeddingProvider

    provider = EmbeddingProvider()

    # Case 1: llama-server 2D array output: [{"index": 0, "embedding": [[0.1, 0.2, 0.3]]}]
    mock_resp1 = MagicMock()
    mock_resp1.__enter__.return_value = mock_resp1
    mock_resp1.read.return_value = json.dumps([{"index": 0, "embedding": [[0.1, 0.2, 0.3]]}]).encode("utf-8")

    with patch("urllib.request.urlopen", return_value=mock_resp1), \
         patch.dict("os.environ", {"LLAMA_SERVER_URL": "http://127.0.0.1:8312"}):
        vec = provider._embed("hello")
        assert vec == [0.1, 0.2, 0.3]

    # Case 2: llama-server dict output: {"embedding": [[0.1, 0.2, 0.3]]}
    mock_resp2 = MagicMock()
    mock_resp2.__enter__.return_value = mock_resp2
    mock_resp2.read.return_value = json.dumps({"embedding": [[0.1, 0.2, 0.3]]}).encode("utf-8")

    with patch("urllib.request.urlopen", return_value=mock_resp2), \
         patch.dict("os.environ", {"LLAMA_SERVER_URL": "http://127.0.0.1:8312"}):
        vec = provider._embed("hello")
        assert vec == [0.1, 0.2, 0.3]

    # Case 3: Ollama standard dict output: {"embedding": [0.1, 0.2, 0.3]}
    mock_resp3 = MagicMock()
    mock_resp3.__enter__.return_value = mock_resp3
    mock_resp3.read.return_value = json.dumps({"embedding": [0.1, 0.2, 0.3]}).encode("utf-8")

    with patch("urllib.request.urlopen", return_value=mock_resp3):
        # No LLAMA_SERVER_URL set
        vec = provider._embed("hello")
        assert vec == [0.1, 0.2, 0.3]


def test_forced_semantic_search(root):
    from unittest.mock import patch
    from memory_os.modules.search import MemorySearcher
    config = _cfg(root)
    node_id = "test-node-sem"
    node = {
        "id": node_id,
        "type": "fact",
        "summary": "Nvidia driver issues on Ubuntu",
        "evidence": [],
        "status": "verified",
        "freshness": datetime.now().isoformat(timespec="seconds"),
        "trust": "verified",
        "related_nodes": [],
        "tags": [],
    }
    _write_jsonl(config.memory_dir / "nodes.jsonl", [node])

    embed_path = config.memory_dir / "embeddings.jsonl"
    embed_path.write_text(
        json.dumps({"id": node_id, "vector": [1.0, 0.0, 0.0]}) + "\n",
        encoding="utf-8",
    )

    searcher = MemorySearcher(config)
    with patch(
        "memory_os.toolkit.embedding_provider.EmbeddingProvider._embed",
        return_value=[1.0, 0.0, 0.0],
    ):
        results = searcher.search_memory("Nvidia driver", semantic=True)

    ids = [r["id"] for r in results]
    assert node_id in ids



def test_infer_edge_type_never_returns_refutes_from_bm25_heuristic():
    # Regression: refutes requires RelationContractRegistry min_create_protocol=7
    # (same trust tier as supersedes/overrides), but _edge_protocol_level()
    # self-assigns that level rather than checking real authorization -- so a
    # source summary merely containing an everyday word like "override" or
    # "deprecate" (common in software engineering prose) was enough to
    # auto-stale unrelated, previously-verified nodes on bm25 co-occurrence
    # alone, with zero actual contradiction between the two nodes.
    refute_trigger_summaries = [
        "We deprecated the old flag in favor of a new override mechanism.",
        "This replaces the previous config and supersedes the legacy path.",
        "The claim contradicts the earlier assumption and negates the plan.",
    ]
    for summary in refute_trigger_summaries:
        result = _infer_edge_type(summary, "fact:some-note", "arch:unrelated-target")
        assert result != "refutes", f"{summary!r} must not infer refutes"


def test_infer_edge_type_falls_through_to_safe_defaults_for_refute_keywords():
    # "override" also matches nothing else -> falls all the way to depends_on
    assert _infer_edge_type("We override the default setting.", "fact:a", "fact:b") == "configures"
    assert _infer_edge_type("This claim contradicts nothing else notable.", "fact:a", "fact:b") == "depends_on"
