import json
from pathlib import Path

from memory_os.core.config import MemoryOSConfig
from memory_os.core.repository import MemoryRepository
from memory_os.core.storage import FileSystemMemoryStorage
from memory_os.modules.search import MemorySearcher


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _node(node_id: str, summary: str) -> dict:
    return {
        "id": node_id,
        "type": "fact",
        "summary": summary,
        "status": "verified",
        "trust": "verified",
        "freshness": "2026-07-01T00:00:00Z",
        "evidence": ["tests/test_retrieval_recall_suite.py"],
        "related_nodes": [],
        "tags": [],
    }


def _config(tmp_path: Path) -> MemoryOSConfig:
    (tmp_path / "memory_os.config.json").write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    return MemoryOSConfig(config_path=str(tmp_path / "memory_os.config.json"))


def test_query_to_nodes_recall_at_5(tmp_path):
    nodes = [
        _node("arch:memory-graph-schema", "nodes jsonl edges jsonl graph schema fts sync index"),
        _node("arch:memory-os-core-layout", "repository patch store search lifecycle validator modules"),
        _node("arch:swarm-protocol", "agent_comm inbox jsonl tmux send keys status report done signal"),
        _node("arch:agent-registry", "tmux_target risk_max system_prompt_file agent registry capabilities"),
        _node("arch:task-lifecycle", "created running done blocked inbox done task events jsonl"),
        _node("strategy:open-items-20260701", "retrieval eval recall at five open items"),
        _node("strategy:collab-agy-codex", "codex implementation tests agy architecture review knowledge curation"),
        _node("strategy:swarm-testing-architecture", "deterministic fake agent e2e suite release gate tmux smoke tests"),
    ]

    questions = [
        ("what stores the graph schema for nodes and edges jsonl", "arch:memory-graph-schema"),
        ("which code area owns repository patch store search lifecycle validator", "arch:memory-os-core-layout"),
        ("how does agent_comm write inbox jsonl and status report done signal", "arch:swarm-protocol"),
        ("where is tmux_target mapped with risk_max and system_prompt_file", "arch:agent-registry"),
        ("what task lifecycle includes created running done blocked and inbox", "arch:task-lifecycle"),
        ("what open item tracks retrieval eval recall at five", "strategy:open-items-20260701"),
        ("who handles implementation tests and knowledge curation", "strategy:collab-agy-codex"),
        ("what release gate uses deterministic fake agent e2e suite", "strategy:swarm-testing-architecture"),
    ]

    _write_jsonl(tmp_path / "memory" / "nodes.jsonl", nodes)
    _write_jsonl(tmp_path / "memory" / "edges.jsonl", [])

    config = _config(tmp_path)
    MemoryRepository(FileSystemMemoryStorage(), config).sync_sqlite()
    searcher = MemorySearcher(config)

    misses = []
    for question, expected_id in questions:
        top_ids = [row["id"] for row in searcher.search_memory(question, depth=0)[:5]]
        if expected_id not in top_ids:
            misses.append({"question": question, "expected": expected_id, "top5": top_ids})

    assert not misses, misses
    assert len(questions) == 8
    assert len(nodes) == 8
