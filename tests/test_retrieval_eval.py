import json
from pathlib import Path
from typing import Optional

from memory_os.core.config import MemoryOSConfig
from memory_os.core.repository import MemoryRepository
from memory_os.core.storage import FileSystemMemoryStorage
from memory_os.modules.search import MemorySearcher


def _cfg(root: Path) -> MemoryOSConfig:
    return MemoryOSConfig(config_path=str(root / "memory_os.config.json"))


def _write_nodes(path: Path, nodes: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(node, ensure_ascii=False) + "\n" for node in nodes),
        encoding="utf-8",
    )


def _node(node_id: str, summary: str, tags: Optional[list[str]] = None) -> dict:
    return {
        "id": node_id,
        "type": "fact",
        "summary": summary,
        "evidence": ["tests/test_retrieval_eval.py"],
        "status": "verified",
        "freshness": "2026-07-01T00:00:00Z",
        "trust": "verified",
        "related_nodes": [],
        "tags": tags or [],
    }


def test_curated_memory_recall_at_5(tmp_path):
    config_path = tmp_path / "memory_os.config.json"
    config_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    config = _cfg(tmp_path)

    nodes = [
        _node(
            "arch:memory-os-core-layout",
            "Memory OS source layout: core repository graph CRUD, modules search lifecycle validator, toolkit agent_comm workspace link_inferrer graph_mapper, adapters telegram_polling, cli subcommands.",
            ["architecture", "layout"],
        ),
        _node(
            "arch:swarm-protocol",
            "Swarm protocol: agent_comm send writes inbox jsonl, sends tmux send-keys to pane, TASK_ASSIGN can use inbox-only fallback, STATUS_REPORT writes done signal.",
            ["swarm", "transport"],
        ),
        _node(
            "arch:memory-graph-schema",
            "Memory graph schema: nodes jsonl has id type summary status trust tags freshness evidence; edges jsonl stores source target type relation; SQLite FTS sync indexes graph_nodes.",
            ["memory", "schema"],
        ),
        _node(
            "arch:agent-registry",
            "Agent registry: agent_context agents registry toml maps agent_id to tmux_target and records capabilities context_window cost_class risk_max system_prompt_file.",
            ["swarm", "registry"],
        ),
        _node(
            "arch:task-lifecycle",
            "Task lifecycle: created running done blocked; task_events jsonl records feed, inbox AGENT jsonl stores payloads, done TASK_ID json is written by STATUS_REPORT.",
            ["task", "lifecycle"],
        ),
        _node(
            "strategy:open-items-20260701",
            "Open items: datetime utcnow cleanup, retrieval eval recall at five, curated knowledge nodes, agy tmux wake audit, sparse graph improvement.",
            ["strategy", "open_items"],
        ),
        _node(
            "strategy:collab-agy-codex",
            "Collaboration protocol agy codex: codex handles implementation tests datetime fixes eval suites; agy handles architecture review knowledge curation swarm coordination tmux audit.",
            ["strategy", "collaboration"],
        ),
    ]
    _write_nodes(config.memory_dir / "nodes.jsonl", nodes)
    _write_nodes(config.memory_dir / "edges.jsonl", [])

    MemoryRepository(FileSystemMemoryStorage(), config).sync_sqlite()
    searcher = MemorySearcher(config)

    cases = [
        ("which code area owns graph CRUD search lifecycle validator", "arch:memory-os-core-layout"),
        ("how does swarm send write inbox and tmux send keys", "arch:swarm-protocol"),
        ("what fields define nodes jsonl status trust evidence tags", "arch:memory-graph-schema"),
        ("where is tmux_target mapped for each agent_id", "arch:agent-registry"),
        ("where does STATUS_REPORT write done TASK_ID json", "arch:task-lifecycle"),
        ("what open item tracks retrieval eval recall at five", "strategy:open-items-20260701"),
        ("who handles implementation tests and who handles knowledge curation", "strategy:collab-agy-codex"),
    ]

    misses = []
    for question, expected_id in cases:
        top_ids = [row["id"] for row in searcher.search_memory(question, depth=0)[:5]]
        if expected_id not in top_ids:
            misses.append({"question": question, "expected": expected_id, "top5": top_ids})

    recall_at_5 = (len(cases) - len(misses)) / len(cases)
    assert recall_at_5 == 1.0, misses


def test_retrieval_eval_uses_top_5_results(tmp_path, monkeypatch):
    from memory_os.toolkit.eval_runner import EvalRunner

    config_path = tmp_path / "memory_os.config.json"
    config_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    config = _cfg(tmp_path)

    evals_dir = tmp_path / "evals" / "retrieval-relevance"
    evals_dir.mkdir(parents=True)
    (evals_dir / "config.json").write_text(
        json.dumps({"kind": "local", "pass_threshold": 1.0}),
        encoding="utf-8",
    )
    (evals_dir / "cases.jsonl").write_text(
        json.dumps({"id": "case-1", "query": "needle", "expected_node_id_substring": "target"}) + "\n",
        encoding="utf-8",
    )

    calls = []

    class FakeSearcher:
        def __init__(self, *args, **kwargs):
            pass

        def search_memory(self, query, depth=1):
            calls.append(depth)
            return [
                {"id": f"node-{idx}", "summary": f"node {idx}"}
                for idx in range(5)
            ] + [{"id": "target-node", "summary": "node 5"}]

    monkeypatch.setattr("memory_os.toolkit.eval_runner.EVALS_DIR", tmp_path / "evals")
    monkeypatch.setattr("memory_os.toolkit.eval_runner.MemorySearcher", FakeSearcher)

    result = EvalRunner(config).run("retrieval-relevance")

    assert result["metric"] == "recall@5/precision@5"
    assert result["recall_at_5"] == 0.0
    assert result["precision_at_5"] == 0.0
    assert result["pass_rate"] == 0.0
    assert calls == [0]


def test_retrieval_eval_supports_expected_any_and_precision_at_5(tmp_path, monkeypatch):
    from memory_os.toolkit.eval_runner import EvalRunner

    config_path = tmp_path / "memory_os.config.json"
    config_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    config = _cfg(tmp_path)

    evals_dir = tmp_path / "evals" / "retrieval-relevance"
    evals_dir.mkdir(parents=True)
    (evals_dir / "config.json").write_text(
        json.dumps({"kind": "local", "pass_threshold": 1.0}),
        encoding="utf-8",
    )
    (evals_dir / "cases.jsonl").write_text(
        json.dumps(
            {
                "id": "case-expected-any",
                "query": "architecture memory",
                "expected_any": ["arch:memory-graph-schema", "strategy:consensus-2026-2027"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    class FakeSearcher:
        def __init__(self, *args, **kwargs):
            pass

        def search_memory(self, query, depth=1):
            return [
                {"id": "arch:memory-graph-schema", "summary": "schema"},
                {"id": "unrelated-1", "summary": "other"},
                {"id": "strategy:consensus-2026-2027", "summary": "roadmap"},
                {"id": "unrelated-2", "summary": "other"},
                {"id": "unrelated-3", "summary": "other"},
            ]

    monkeypatch.setattr("memory_os.toolkit.eval_runner.EVALS_DIR", tmp_path / "evals")
    monkeypatch.setattr("memory_os.toolkit.eval_runner.MemorySearcher", FakeSearcher)

    result = EvalRunner(config).run("retrieval-relevance")

    assert result["ok"] is True
    assert result["recall_at_5"] == 1.0
    assert result["precision_at_5"] == 0.4
    assert result["cases"][0]["expected_any"] == ["arch:memory-graph-schema", "strategy:consensus-2026-2027"]


def test_retrieval_eval_supports_absent_substring_negative_cases(tmp_path, monkeypatch):
    from memory_os.toolkit.eval_runner import EvalRunner

    config_path = tmp_path / "memory_os.config.json"
    config_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    config = _cfg(tmp_path)

    evals_dir = tmp_path / "evals" / "retrieval-relevance"
    evals_dir.mkdir(parents=True)
    (evals_dir / "config.json").write_text(
        json.dumps({"kind": "local", "pass_threshold": 1.0}),
        encoding="utf-8",
    )
    (evals_dir / "cases.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"id": "negative-pass", "query": "schema", "expect_absent_substring": "stale-lowconf"}),
                json.dumps({"id": "negative-fail", "query": "schema", "expect_absent_substring": "forbidden-node"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    class FakeSearcher:
        def __init__(self, *args, **kwargs):
            pass

        def search_memory(self, query, depth=1):
            return [{"id": "forbidden-node", "summary": "should not be in top results"}]

    monkeypatch.setattr("memory_os.toolkit.eval_runner.EVALS_DIR", tmp_path / "evals")
    monkeypatch.setattr("memory_os.toolkit.eval_runner.MemorySearcher", FakeSearcher)

    result = EvalRunner(config).run("retrieval-relevance")

    assert result["recall_at_5"] == 0.0
    assert result["precision_at_5"] == 0.0
    assert result["pass_rate"] == 0.5
    assert result["cases"][0]["passed"] is True
    assert result["cases"][1]["passed"] is False


def test_retrieval_eval_suite_metadata_includes_runtime_focus(tmp_path, monkeypatch):
    from memory_os.toolkit.eval_runner import EvalRunner

    config_path = tmp_path / "memory_os.config.json"
    config_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    config = _cfg(tmp_path)

    suite_dir = tmp_path / "evals" / "retrieval-relevance"
    suite_dir.mkdir(parents=True)
    (suite_dir / "config.json").write_text(
        json.dumps({
            "kind": "local",
            "pass_threshold": 0.66,
            "description": "Offline retrieval relevance checks against MemorySearcher search results for the memory runtime.",
        }),
        encoding="utf-8",
    )
    (suite_dir / "cases.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "id": f"case-{idx}",
                    "query": f"query {idx}",
                    "expected_node_id_substring": "target",
                }
            )
            for idx in range(12)
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("memory_os.toolkit.eval_runner.EVALS_DIR", tmp_path / "evals")

    suites = EvalRunner(config).list_suites()
    retrieval_suite = next(item for item in suites if item["name"] == "retrieval-relevance")

    assert retrieval_suite["case_count"] == 12
    assert "memory runtime" in retrieval_suite["description"]


def test_search_ranks_high_confidence_above_low(tmp_path):
    """Phase 3: equal lexical match — verified full-confidence node must outrank a low-confidence draft."""
    import json
    from memory_os.core.config import MemoryOSConfig

    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    (tmp_path / "memory_os.config.json").write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    nodes = [
        {"id": "fact:lowconf-widget", "type": "fact", "summary": "widget frobnicator details", "status": "draft", "confidence": 0.2, "evidence": []},
        {"id": "fact:highconf-widget", "type": "fact", "summary": "widget frobnicator details", "status": "verified", "confidence": 1.0, "evidence": []},
    ]
    (tmp_path / "memory" / "nodes.jsonl").write_text(
        "\n".join(json.dumps(n) for n in nodes) + "\n", encoding="utf-8"
    )
    (tmp_path / "memory" / "edges.jsonl").write_text("", encoding="utf-8")

    import os
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        config = MemoryOSConfig(str(tmp_path / "memory_os.config.json"))
        from memory_os.modules.search import MemorySearcher
        searcher = MemorySearcher(config)
        results = searcher.search_memory("widget frobnicator", depth=0)
    finally:
        os.chdir(cwd)

    ids = [r["id"] for r in results]
    assert ids.index("fact:highconf-widget") < ids.index("fact:lowconf-widget")


def test_retrieval_eval_precision_at_5_uses_returned_count_not_fixed_k(tmp_path, monkeypatch):
    """Regression: precision@5 = relevant / top_k (fixed 5) structurally caps
    precision at 1/5=0.2 for single-answer factual queries even when the
    search returns exactly the one correct node and nothing else -- that's
    perfect precision (1/1), not 20% precision. Must divide by the actual
    number of results returned, per the standard IR definition of precision@k."""
    from memory_os.toolkit.eval_runner import EvalRunner

    config_path = tmp_path / "memory_os.config.json"
    config_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    config = _cfg(tmp_path)

    evals_dir = tmp_path / "evals" / "retrieval-relevance"
    evals_dir.mkdir(parents=True)
    (evals_dir / "config.json").write_text(
        json.dumps({"kind": "local", "pass_threshold": 1.0}),
        encoding="utf-8",
    )
    (evals_dir / "cases.jsonl").write_text(
        json.dumps({"id": "single-answer", "query": "unique thing", "expected_node_id_substring": "the-one-node"}) + "\n",
        encoding="utf-8",
    )

    class FakeSearcher:
        def __init__(self, *args, **kwargs):
            pass

        def search_memory(self, query, depth=1):
            # Only one truly relevant node exists in the whole graph, and the
            # search correctly returns exactly it -- nothing else, no padding.
            return [{"id": "the-one-node", "summary": "the correct answer"}]

    monkeypatch.setattr("memory_os.toolkit.eval_runner.EVALS_DIR", tmp_path / "evals")
    monkeypatch.setattr("memory_os.toolkit.eval_runner.MemorySearcher", FakeSearcher)

    result = EvalRunner(config).run("retrieval-relevance")

    assert result["cases"][0]["precision_at_5"] == 1.0
    assert result["precision_at_5"] == 1.0
    assert result["recall_at_5"] == 1.0
