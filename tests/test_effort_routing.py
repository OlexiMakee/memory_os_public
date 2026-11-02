"""Tests for quantizer-derived effort routing in task dispatch."""

from memory_os.toolkit.quantizer import (
    EFFORT_RULES,
    calculate_level,
    effort_directive,
    effort_for_level,
)


def test_effort_tiers_map_to_level_bands():
    assert effort_for_level(0) == "low"
    assert effort_for_level(4) == "low"
    assert effort_for_level(5) == "medium"
    assert effort_for_level(8) == "medium"
    assert effort_for_level(9) == "high"
    assert effort_for_level(13) == "high"


def test_effort_directive_simple_task_is_low():
    d = effort_directive("fix typo in README comment")
    assert d.startswith("[EFFORT low L")
    assert "touched test file" in d or "no tests" in d


def test_effort_directive_risky_task_is_high():
    d = effort_directive(
        "refactor database schema migration architecture", 
    )
    assert "[EFFORT high" in d or "[EFFORT medium" in d
    level = calculate_level("refactor database schema migration architecture")
    assert level >= 5


def test_effort_directive_explicit_override():
    d = effort_directive("refactor database schema architecture", effort="low")
    assert d.startswith("[EFFORT low L")
    # level in header still reflects the true quantizer level
    level = calculate_level("refactor database schema architecture")
    assert f"L{level}]" in d


def test_effort_directive_invalid_override_falls_back_to_auto():
    d = effort_directive("fix typo", effort="turbo")
    assert d.startswith("[EFFORT low L")


def test_send_task_message_carries_effort_header(tmp_path, monkeypatch):
    import json as _json
    (tmp_path / "memory_os.config.json").write_text(_json.dumps({"version": "0.1"}), encoding="utf-8")

    captured = {}

    class FakeResult:
        ok = True

    class FakeComm:
        def __init__(self, *a, **kw):
            pass

        def send(self, **kwargs):
            captured.update(kwargs)
            return FakeResult()

    import memory_os.toolkit.workspace as ws
    monkeypatch.setattr("memory_os.toolkit.agent_comm.AgentComm", FakeComm)
    monkeypatch.chdir(tmp_path)

    ok = ws.send_task(agent_id="codex", task_id="task_eff1", prompt="fix typo in docs")
    assert ok
    assert "[EFFORT low L" in captured["message"]
    assert "[TASK task_eff1]" in captured["message"]
