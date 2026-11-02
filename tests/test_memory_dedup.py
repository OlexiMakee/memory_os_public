import json
from pathlib import Path

from memory_os.cli import cmd_memory_dedup_candidates
from memory_os.core.config import MemoryOSConfig
from memory_os.toolkit.memory_graph_service import MemoryGraphService


def make_config(tmp_path: Path) -> MemoryOSConfig:
    (tmp_path / "memory").mkdir(exist_ok=True)
    (tmp_path / "agent_context").mkdir(exist_ok=True)
    (tmp_path / "memory" / "nodes.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "edges.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "events.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory_os.config.json").write_text(
        json.dumps({"version": "0.1", "memory_dir": "memory", "db_path": "memory/memory_os.db"}),
        encoding="utf-8",
    )
    return MemoryOSConfig(str(tmp_path / "memory_os.config.json"))


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def test_dedup_candidates_generator_and_cli(tmp_path, capsys):
    config = make_config(tmp_path)
    
    # 1. Write synthetic nodes
    _write_jsonl(
        config.memory_dir / "nodes.jsonl",
        [
            {
                "id": "fact:alpha",
                "type": "fact",
                "summary": "This is a simple test summary for alpha",
                "status": "verified",
                "confidence": 0.95
            },
            {
                "id": "fact:beta",
                "type": "fact",
                "summary": "This is a simple test summary for alpha", # Near-identical (Jaccard = 1.0)
                "status": "verified",
                "confidence": 0.8
            },
            {
                "id": "fact:gamma",
                "type": "fact",
                "summary": "Totally different random text summary here",
                "status": "verified",
                "confidence": 0.9
            },
            {
                "id": "rule:delta",
                "type": "rule",
                "summary": "Delta summary is different",
                "status": "verified",
                "confidence": 0.85
            },
            {
                "id": "rule:epsilon",
                "type": "rule",
                "summary": "Epsilon summary is also different", # Embeddings will match this
                "status": "verified",
                "confidence": 0.7
            },
            {
                "id": "policy:zeta",
                "type": "policy",
                "summary": "This is a simple test summary for alpha", # Jaccard matches fact:alpha, but policy is ignored
                "status": "verified",
                "confidence": 0.9
            }
        ]
    )
    
    # 2. Write synthetic embeddings cache
    _write_jsonl(
        config.memory_dir / "embeddings.jsonl",
        [
            {"id": "fact:alpha", "model": "nomic-embed-text", "vector": [1.0, 0.0, 0.0]},
            {"id": "fact:beta", "model": "nomic-embed-text", "vector": [0.0, 1.0, 0.0]}, # low cosine similarity
            {"id": "fact:gamma", "model": "nomic-embed-text", "vector": [0.0, 0.0, 1.0]},
            {"id": "rule:delta", "model": "nomic-embed-text", "vector": [0.707, 0.707, 0.0]},
            {"id": "rule:epsilon", "model": "nomic-embed-text", "vector": [0.708, 0.706, 0.0]}, # high cosine similarity (~0.999)
            {"id": "policy:zeta", "model": "nomic-embed-text", "vector": [1.0, 0.0, 0.0]}
        ]
    )
    
    # Test generator method directly
    service = MemoryGraphService(config)
    candidates = service.get_dedup_candidates()
    
    # Assertions on direct candidates list
    assert len(candidates) == 2
    
    # Candidate 1: Jaccard match between fact:alpha and fact:beta
    pair1 = next(c for c in candidates if c["node_a_id"] == "fact:alpha" and c["node_b_id"] == "fact:beta")
    assert pair1["jaccard"] == 1.0
    assert pair1["cosine"] == 0.0
    
    # Candidate 2: Cosine similarity match between rule:delta and rule:epsilon
    pair2 = next(c for c in candidates if c["node_a_id"] == "rule:delta" and c["node_b_id"] == "rule:epsilon")
    assert pair2["cosine"] > 0.99
    
    # Verify policy:zeta is ignored
    assert not any(c["node_a_id"] == "policy:zeta" or c["node_b_id"] == "policy:zeta" for c in candidates)
    
    # Test CLI output in Text format
    capsys.readouterr() # clear buffers
    code = cmd_memory_dedup_candidates(type("Args", (), {"format": "text", "limit": None})(), config)
    assert code == 0
    text_out = capsys.readouterr().out
    assert "Found 2 candidate pairs." in text_out
    assert "Pair: fact:alpha <-> fact:beta" in text_out
    assert "Pair: rule:delta <-> rule:epsilon" in text_out
    assert "Merge Command: memory_os memory merge-preview fact:alpha fact:beta" in text_out

    code_json = cmd_memory_dedup_candidates(type("Args", (), {"format": "json", "limit": 1})(), config)
    assert code_json == 0
    json_out = json.loads(capsys.readouterr().out)
    assert len(json_out) == 1
    assert json_out[0]["node_a_id"] == "fact:alpha"
    assert json_out[0]["node_b_id"] == "fact:beta"
    assert json_out[0]["jaccard"] == 1.0


def test_dedup_candidates_support_focused_draft_to_verified_triage(tmp_path):
    config = make_config(tmp_path)
    _write_jsonl(
        config.memory_dir / "nodes.jsonl",
        [
            {"id": "policy:draft", "type": "policy", "summary": "rotate audit archive safely", "status": "draft"},
            {"id": "policy:verified", "type": "policy", "summary": "rotate audit logs safely", "status": "verified"},
            {"id": "policy:other", "type": "policy", "summary": "unrelated desktop setting", "status": "verified"},
        ],
    )

    candidates = MemoryGraphService(config).get_dedup_candidates(
        focus_ids={"policy:draft"},
        candidate_status="verified",
        include_all_types=True,
        min_cosine=0.4,
        min_jaccard=0.4,
    )

    assert len(candidates) == 1
    assert {candidates[0]["node_a_id"], candidates[0]["node_b_id"]} == {
        "policy:draft",
        "policy:verified",
    }
