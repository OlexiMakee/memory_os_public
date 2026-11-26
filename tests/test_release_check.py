import json
from pathlib import Path

from memory_os.core.config import MemoryOSConfig
from memory_os.core.release_check import ReleaseChecker


def make_release_root(tmp_path: Path) -> MemoryOSConfig:
    (tmp_path / "agent_context").mkdir()
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "nodes.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "edges.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "events.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "agent_context" / "task_capsules.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory_os.config.json").write_text(
        json.dumps({
            "memory_dir": "memory",
            "db_path": "memory/memory_os.db",
            "daemon_port": 0,
        }),
        encoding="utf-8",
    )
    return MemoryOSConfig(str(tmp_path / "memory_os.config.json"))


def test_release_check_includes_eval_gate(tmp_path, monkeypatch):
    config = make_release_root(tmp_path)

    monkeypatch.setattr(
        "memory_os.core.release_check.ReleaseChecker._check_validate",
        lambda self: type("Check", (), {"to_dict": lambda self: {"name": "validate", "ok": True, "detail": "ok", "severity": "error"}, "ok": True, "severity": "error"})(),
    )
    monkeypatch.setattr(
        "memory_os.core.release_check.ReleaseChecker._check_default_security",
        lambda self: type("Check", (), {"to_dict": lambda self: {"name": "security-default", "ok": True, "detail": "ok", "severity": "error"}, "ok": True, "severity": "error"})(),
    )
    monkeypatch.setattr(
        "memory_os.core.release_check.ReleaseChecker._check_context_privacy",
        lambda self: type("Check", (), {"to_dict": lambda self: {"name": "context-private-leak", "ok": True, "detail": "ok", "severity": "error"}, "ok": True, "severity": "error"})(),
    )
    monkeypatch.setattr(
        "memory_os.core.release_check.ReleaseChecker._check_docs_hygiene",
        lambda self: type("Check", (), {"to_dict": lambda self: {"name": "docs-hygiene", "ok": True, "detail": "ok", "severity": "error"}, "ok": True, "severity": "error"})(),
    )
    monkeypatch.setattr(
        "memory_os.core.release_check.ReleaseChecker._check_core_dependencies",
        lambda self: type("Check", (), {"to_dict": lambda self: {"name": "core-dependencies", "ok": True, "detail": "ok", "severity": "error"}, "ok": True, "severity": "error"})(),
    )
    monkeypatch.setattr(
        "memory_os.core.release_check.ReleaseChecker._check_resources",
        lambda self: type("Check", (), {"to_dict": lambda self: {"name": "resources", "ok": True, "detail": "ok", "severity": "error"}, "ok": True, "severity": "error"})(),
    )
    monkeypatch.setattr(
        "memory_os.core.release_check.ReleaseChecker._check_write_budget",
        lambda self: type("Check", (), {"to_dict": lambda self: {"name": "write-budget", "ok": True, "detail": "ok", "severity": "error"}, "ok": True, "severity": "error"})(),
    )
    monkeypatch.setattr(
        "memory_os.core.release_check.ReleaseChecker._check_telemetry",
        lambda self: type("Check", (), {"to_dict": lambda self: {"name": "telemetry-budget", "ok": True, "detail": "ok", "severity": "error"}, "ok": True, "severity": "error"})(),
    )

    eval_result = {"ok": True, "pass_rate": 1.0, "pass_threshold": 1.0}

    class FakeEvalRunner:
        def __init__(self, config):
            self.config = config

        def run(self, suite):
            assert suite == "retrieval-relevance"
            return eval_result

    monkeypatch.setattr("memory_os.core.release_check.EvalRunner", FakeEvalRunner, raising=False)

    result = ReleaseChecker(config).run(target="private")

    assert result["ok"] is True
    assert any(check["name"] == "eval-gate" for check in result["checks"])
    assert any(check["name"] == "validate" for check in result["checks"])


def test_release_check_fails_when_eval_gate_fails(tmp_path, monkeypatch):
    config = make_release_root(tmp_path)

    monkeypatch.setattr("memory_os.core.release_check.ReleaseChecker._check_validate", lambda self: _ok_check("validate"))
    monkeypatch.setattr("memory_os.core.release_check.ReleaseChecker._check_default_security", lambda self: _ok_check("security-default"))
    monkeypatch.setattr("memory_os.core.release_check.ReleaseChecker._check_context_privacy", lambda self: _ok_check("context-private-leak"))
    monkeypatch.setattr("memory_os.core.release_check.ReleaseChecker._check_docs_hygiene", lambda self: _ok_check("docs-hygiene"))
    monkeypatch.setattr("memory_os.core.release_check.ReleaseChecker._check_core_dependencies", lambda self: _ok_check("core-dependencies"))
    monkeypatch.setattr("memory_os.core.release_check.ReleaseChecker._check_resources", lambda self: _ok_check("resources"))
    monkeypatch.setattr("memory_os.core.release_check.ReleaseChecker._check_write_budget", lambda self: _ok_check("write-budget"))
    monkeypatch.setattr("memory_os.core.release_check.ReleaseChecker._check_telemetry", lambda self: _ok_check("telemetry-budget"))

    class FakeEvalRunner:
        def __init__(self, config):
            self.config = config

        def run(self, suite):
            return {"ok": False, "pass_rate": 0.5, "pass_threshold": 1.0}

    monkeypatch.setattr("memory_os.core.release_check.EvalRunner", FakeEvalRunner, raising=False)

    result = ReleaseChecker(config).run(target="private")

    assert result["ok"] is False
    eval_gate = next(check for check in result["checks"] if check["name"] == "eval-gate")
    assert eval_gate["ok"] is False
    assert "retrieval-relevance=0.50<1.0" in eval_gate["detail"]


def test_release_check_flags_direct_canonical_graph_writes(tmp_path):
    config = make_release_root(tmp_path)
    source_dir = tmp_path / "src" / "memory_os"
    source_dir.mkdir(parents=True)
    (source_dir / "bad_writer.py").write_text(
        """
from pathlib import Path


def write_graph(storage):
    nodes_path = Path("memory") / "nodes.jsonl"
    storage.save_jsonl(nodes_path, [])
""",
        encoding="utf-8",
    )

    check = ReleaseChecker(config)._check_graph_write_path()

    assert check.ok is False
    assert "bad_writer.py:7" in check.detail


def test_release_check_public_clean_room_passes_on_clean_tree(tmp_path):
    config = make_release_root(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "memory_os"\n', encoding="utf-8")
    (tmp_path / "README.md").write_text("# Memory OS\n", encoding="utf-8")

    check = ReleaseChecker(config)._check_public_clean_room()

    assert check.ok is True
    assert check.name == "public-clean-room"


def test_release_check_public_clean_room_flags_forbidden_paths_and_patterns(tmp_path):
    config = make_release_root(tmp_path)
    forbidden_mod = tmp_path / "src" / "memory_os" / "ide_grant_private.py"
    forbidden_mod.parent.mkdir(parents=True)
    forbidden_mod.write_text("# private\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "# When used inside this host project — LLMClientFactory is resolved automatically.\n",
        encoding="utf-8",
    )

    check = ReleaseChecker(config)._check_public_clean_room()

    assert check.ok is False
    assert "forbidden-path:src/memory_os/ide_grant_private.py" in check.detail
    assert "clean-room-pattern:pyproject.toml" in check.detail


def _ok_check(name: str):
    class Check:
        ok = True
        severity = "error"

        def to_dict(self):
            return {"name": name, "ok": True, "detail": "ok", "severity": "error"}

    return Check()
