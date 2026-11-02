"""Tests for RouterPlan (Phase 3 — deterministic routing)."""
import json
from pathlib import Path
import pytest
from memory_os.toolkit.router_plan import RouterPlan
from memory_os.toolkit.task_kernel import TaskKernel


REGISTRY_TOML = """
[agent.local-router]
kind = "local_model"
command = ["ollama", "run", "qwen3:4b"]
capabilities = ["classify", "tool_intent", "summarize_output"]
cost_class = "cheap"
risk_max = "low"

[agent.memory-os-cli]
kind = "script"
command = ["python3", "-m", "memory_os"]
capabilities = ["memory.search", "memory.write", "eval.run", "audit"]
cost_class = "zero"
risk_max = "medium"

[agent.shell]
kind = "shell"
command = ["bash"]
capabilities = ["run_tests", "lint", "git"]
cost_class = "zero"
risk_max = "medium"

[agent.claude]
kind = "cli_agent"
command = ["claude"]
capabilities = ["code_edit", "architecture", "review", "deep_context"]
cost_class = "limited"
risk_max = "high"
"""


@pytest.fixture
def root(tmp_path):
    # Write minimal registry.toml (local-router needs ollama in PATH — we'll test without it)
    (tmp_path / "agent_context" / "agents").mkdir(parents=True)
    (tmp_path / "agent_context" / "agents" / "registry.toml").write_text(
        REGISTRY_TOML, encoding="utf-8"
    )
    (tmp_path / "memory_os.config.json").write_text(
        json.dumps({"version": "0.1"}), encoding="utf-8"
    )
    return tmp_path


def test_route_memory_search_picks_script(root):
    plan = RouterPlan(root).route(text="search memory", risk="low", capabilities=["memory.search"])
    assert plan.agent_kind == "script"
    assert plan.estimated_cost == "zero"
    assert plan.requires_review is False


def test_route_high_risk_picks_cli_agent_and_requires_review(root, monkeypatch):
    monkeypatch.setattr("memory_os.toolkit.agent_health.AgentHealthProbe.check", lambda self, *a, **k: {"status": "ok"})
    plan = RouterPlan(root).route(text="refactor module", risk="high", capabilities=["code_edit"])
    assert plan.agent_kind == "cli_agent"
    assert plan.requires_review is True


def test_route_run_tests_picks_shell(root):
    plan = RouterPlan(root).route(text="run tests", risk="low", capabilities=["run_tests"])
    assert plan.agent_kind in ("shell", "script")
    assert plan.estimated_cost == "zero"


def test_route_from_task_id(root):
    kernel = TaskKernel(root)
    task = kernel.create("audit memory", goal="run audit", risk="low", capabilities=["audit"])
    plan = RouterPlan(root).route(task_id=task["id"])
    assert plan.task_id == task["id"]
    assert plan.agent_kind in ("script", "shell", "local_model")


def test_route_missing_task_raises(root):
    with pytest.raises(KeyError):
        RouterPlan(root).route(task_id="task_nonexistent")


def test_plan_to_dict_has_required_fields(root):
    plan = RouterPlan(root).route(text="classify", risk="low", capabilities=["classify"])
    d = plan.to_dict()
    for key in ("agent", "agent_kind", "mode", "estimated_cost", "requires_review",
                "fallback", "rationale", "budget_degraded"):
        assert key in d


def test_no_registry_returns_fallback(tmp_path):
    # No registry.toml → should still return a valid plan (fallback)
    (tmp_path / "agent_context").mkdir()
    plan = RouterPlan(tmp_path).route(text="do something", risk="low")
    assert plan.agent is not None
    assert plan.agent_kind is not None


def test_budget_degraded_flag_not_set_by_default(root):
    plan = RouterPlan(root).route(text="any task", risk="low")
    # Without a real RoutingPolicy + exhausted budget, this should be False
    assert plan.budget_degraded is False


def test_local_model_available_via_ollama_http_without_cli(root, monkeypatch):
    monkeypatch.setattr("memory_os.toolkit.agent_health.shutil.which", lambda binary: None if binary == "ollama" else f"/usr/bin/{binary}")
    monkeypatch.setattr("memory_os.core.llm_service.ollama_http_health", lambda timeout=1.5: {"ok": True, "host": "http://localhost:11434", "model": "qwen3:4b"})
    monkeypatch.setattr("memory_os.toolkit.router_plan._ollama_http_available", lambda: True)

    plan = RouterPlan(root).route(text="classify", risk="low", capabilities=["classify"])

    assert plan.agent == "local-router"
    assert plan.agent_kind == "local_model"


@pytest.mark.parametrize("capability", ["code_edit", "architecture", "deep_context", "repro_analysis"])
def test_route_blocks_cli_required_work_when_no_cli_agent_is_available(root, monkeypatch, capability):
    monkeypatch.setattr(
        "memory_os.toolkit.agent_health.AgentHealthProbe.check",
        lambda self, agent_id, **kwargs: {"status": "quota_exhausted"},
    )

    plan = RouterPlan(root).route(
        text="implement source indexing",
        risk="medium",
        capabilities=[capability],
    )

    assert plan.agent_kind == "unavailable"
    assert plan.mode == "blocked"
    assert plan.blocked_reason
    assert "cli_agent" in plan.blocked_reason
