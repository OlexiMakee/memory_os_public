"""Tests for DispatcherEngine (Phase 4 — dispatch adapters)."""
import json
import subprocess
from pathlib import Path
import pytest
from memory_os.toolkit.dispatcher import CliAgentAdapter, DispatcherEngine
from memory_os.toolkit.task_kernel import TaskKernel


@pytest.fixture
def root(tmp_path):
    (tmp_path / "agent_context").mkdir()
    (tmp_path / "memory_os.config.json").write_text(
        json.dumps({"version": "0.1"}), encoding="utf-8"
    )
    return tmp_path


def test_shell_dry_run(root):
    d = DispatcherEngine(root)
    result = d.shell(None, ["echo", "test"], dry_run=True)
    assert result.ok is True
    assert result.dry_run is True
    assert result.exit_code is None
    assert "dry-run" in result.stdout


def test_shell_real_command(root):
    d = DispatcherEngine(root)
    result = d.shell(None, ["echo", "hello"], dry_run=False)
    assert result.ok is True
    assert result.exit_code == 0
    assert "hello" in result.stdout


def test_shell_failing_command(root):
    d = DispatcherEngine(root)
    result = d.shell(None, ["false"], dry_run=False)
    assert result.ok is False
    assert result.exit_code != 0


def test_shell_writes_evidence_when_task_id_given(root):
    kernel = TaskKernel(root)
    task = kernel.create("test task", risk="low")
    kernel.claim(task["id"], "test-agent")
    kernel.start(task["id"])

    d = DispatcherEngine(root)
    result = d.shell(task["id"], ["echo", "dispatch"], dry_run=False)
    assert result.evidence_path is not None
    assert Path(result.evidence_path).exists()
    evidence = json.loads(Path(result.evidence_path).read_text())
    assert evidence["task_id"] == task["id"]
    assert evidence["ok"] is True


def test_shell_done_updates_task_status(root):
    kernel = TaskKernel(root)
    task = kernel.create("shell task", risk="low")
    kernel.claim(task["id"], "shell-agent")
    kernel.start(task["id"])

    d = DispatcherEngine(root)
    d.shell(task["id"], ["echo", "done"], dry_run=False)

    updated = kernel.get(task["id"])
    assert updated["status"] == "done"


def test_shell_failure_blocks_task(root):
    kernel = TaskKernel(root)
    task = kernel.create("fail task", risk="low")
    kernel.claim(task["id"], "shell-agent")
    kernel.start(task["id"])

    d = DispatcherEngine(root)
    d.shell(task["id"], ["false"], dry_run=False)

    updated = kernel.get(task["id"])
    assert updated["status"] == "blocked"


def test_script_dry_run(root):
    d = DispatcherEngine(root)
    result = d.script(None, ["validate"], dry_run=True)
    assert result.ok is True
    assert result.dry_run is True
    assert "dry-run" in result.stdout


def test_script_real_run_validate(root):
    d = DispatcherEngine(root)
    result = d.script(None, ["--help"], dry_run=False, timeout=10.0)
    # --help exits 0 and prints usage
    assert result.ok is True or result.exit_code is not None


def test_dispatch_result_to_dict(root):
    d = DispatcherEngine(root)
    result = d.shell(None, ["echo", "x"], dry_run=True)
    dct = result.to_dict()
    for key in ("ok", "adapter", "agent", "exit_code", "stdout", "stderr",
                "duration_sec", "dry_run", "error"):
        assert key in dct


def test_dispatch_plan_rejects_blocked_route(root):
    class BlockedPlan:
        task_id = None
        agent = "unavailable"
        agent_kind = "unavailable"
        text = "edit code"
        blocked_reason = "No available cli_agent"

    result = DispatcherEngine(root).dispatch_plan(BlockedPlan())

    assert result.ok is False
    assert result.adapter == "blocked"
    assert result.error == BlockedPlan.blocked_reason


def test_shell_done_writes_task_memory_node(root):
    """Successful dispatch should propose a MemoryNode for the completed task."""
    (root / "memory").mkdir()
    kernel = TaskKernel(root)
    task = kernel.create("test memory bridge task", goal="verify memory writing", risk="low")
    kernel.claim(task["id"], "test-agent")
    kernel.start(task["id"])

    d = DispatcherEngine(root)
    d.shell(task["id"], ["echo", "done"], dry_run=False)

    nodes_path = root / "memory" / "nodes.jsonl"
    assert nodes_path.exists(), "nodes.jsonl should be created by _write_task_memory"
    lines = [l for l in nodes_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert lines, "at least one MemoryNode should be written"
    node = json.loads(lines[-1])
    assert "test memory bridge task" in node["summary"].lower()
    assert node["type"] == "fact"
    assert "task_result" in node.get("tags", [])


def test_write_handoff_memory_creates_node(root):
    """_write_handoff_memory should propose a MemoryNode before CLI dispatch."""
    (root / "memory").mkdir()
    kernel = TaskKernel(root)
    task = kernel.create("handoff test task", goal="test handoff memory", risk="medium")

    d = DispatcherEngine(root)
    d._write_handoff_memory(task["id"], "claude")

    nodes_path = root / "memory" / "nodes.jsonl"
    assert nodes_path.exists(), "nodes.jsonl should be created by _write_handoff_memory"
    lines = [l for l in nodes_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert lines, "handoff node should be written"
    node = json.loads(lines[-1])
    assert "handoff" in node["summary"].lower()
    assert "claude" in node["summary"].lower()
    assert node["id"].startswith("handoff:")
    assert "handoff" in node.get("tags", [])


def write_agent_registry(root: Path) -> None:
    registry_dir = root / "agent_context" / "agents"
    registry_dir.mkdir(parents=True, exist_ok=True)
    (registry_dir / "registry.toml").write_text(
        """
[agent.claude]
kind = "cli_agent"
command = ["claude"]
dispatch_flags = ["--dangerously-skip-permissions"]

[agent.codex]
kind = "cli_agent"
command = ["codex", "exec"]
dispatch_flags = ["--sandbox", "danger-full-access", "--ask-for-approval", "never"]

[agent.agy]
kind = "cli_agent"
command = ["agy"]
dispatch_flags = ["--dangerously-skip-permissions"]
""",
        encoding="utf-8",
    )


def test_cli_agent_adapter_builds_codex_command_from_registry(root):
    write_agent_registry(root)
    adapter = CliAgentAdapter(root)
    cmd = adapter.build_command("codex", "do work")
    assert cmd[:2] == ["codex", "exec"]
    assert "-C" in cmd
    assert str(root) in cmd
    assert "--sandbox" in cmd
    assert "danger-full-access" in cmd
    assert "--ask-for-approval" in cmd
    assert "never" in cmd
    assert cmd[-1] == "do work"


def test_cli_agent_adapter_builds_agy_flags_before_prompt(root):
    write_agent_registry(root)
    adapter = CliAgentAdapter(root)
    cmd = adapter.build_command("agy", "do work")
    assert cmd[:2] == ["agy", "--dangerously-skip-permissions"]
    assert cmd[-2:] == ["-p", "do work"]


def test_cli_agent_adapter_supervised_profile_strips_unattended_flags(root):
    from memory_os.toolkit.startup_profile import record_startup_profile

    write_agent_registry(root)
    record_startup_profile(root, "supervised")
    adapter = CliAgentAdapter(root)

    cmd = adapter.build_command("agy", "do work")
    assert "--dangerously-skip-permissions" not in cmd

    cmd = adapter.build_command("codex", "do work")
    assert "--sandbox" not in cmd
    assert "--ask-for-approval" not in cmd


def test_cli_agent_writes_evidence_and_marks_done(root, monkeypatch):
    write_agent_registry(root)
    (root / "memory").mkdir()
    kernel = TaskKernel(root)
    task = kernel.create("cli task", goal="run codex non-interactively", risk="medium")
    kernel.claim(task["id"], "codex")
    kernel.start(task["id"])

    captured = {}

    def fake_which(binary):
        return f"/usr/bin/{binary}"

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        return subprocess.CompletedProcess(cmd, 0, stdout="agent done", stderr="")

    monkeypatch.setattr("memory_os.toolkit.dispatcher.shutil.which", fake_which)
    monkeypatch.setattr("memory_os.toolkit.dispatcher.subprocess.run", fake_run)

    result = DispatcherEngine(root).cli_agent(task["id"], "codex", timeout=10)

    assert result.ok is True
    assert result.exit_code == 0
    assert result.evidence_path is not None
    assert Path(result.evidence_path).exists()
    assert kernel.get(task["id"])["status"] == "done"
    assert captured["cmd"][:2] == ["codex", "exec"]
    assert captured["cwd"] == str(root)
    assert "Memory OS Task Dispatch" in captured["cmd"][-1]

    evidence = json.loads(Path(result.evidence_path).read_text(encoding="utf-8"))
    assert evidence["adapter"] == "cli_agent_codex"
    assert evidence["agent"] == "codex"
    assert evidence["stdout"] == "agent done"


def test_cli_agent_missing_binary_writes_evidence_and_blocks_task(root, monkeypatch):
    write_agent_registry(root)
    kernel = TaskKernel(root)
    task = kernel.create("missing cli task", risk="medium")
    kernel.claim(task["id"], "codex")
    kernel.start(task["id"])

    monkeypatch.setattr("memory_os.toolkit.dispatcher.shutil.which", lambda _binary: None)

    result = DispatcherEngine(root).cli_agent(task["id"], "codex", timeout=10)

    assert result.ok is False
    assert "binary not found" in (result.error or "")
    assert result.evidence_path is not None
    assert Path(result.evidence_path).exists()
    assert kernel.get(task["id"])["status"] == "blocked"


def test_cli_agent_dry_run_does_not_write_evidence(root):
    write_agent_registry(root)
    kernel = TaskKernel(root)
    task = kernel.create("dry cli task", risk="medium")

    result = DispatcherEngine(root).cli_agent(task["id"], "agy", dry_run=True)

    assert result.ok is True
    assert result.dry_run is True
    assert result.evidence_path is None
    assert not (root / "agent_context" / "evidence" / task["id"]).exists()


def test_local_model_uses_local_first_fallback_provider(root, monkeypatch):
    d = DispatcherEngine(root)
    captured = {}

    def fake_call_llm(self, **kwargs):
        captured.update(kwargs)
        return "local answer"

    monkeypatch.setattr(
        "memory_os.core.llm_service.DefaultLlmProviderService.call_llm",
        fake_call_llm,
    )

    result = d.local_model(None, "classify this", dry_run=False)

    assert result.ok is True
    assert result.stdout == "local answer"
    assert captured["provider"] is None
    assert captured["max_tokens"] == 200


def test_local_model_completion_syncs_task_memory_to_sqlite(root, monkeypatch):
    (root / "memory").mkdir()
    kernel = TaskKernel(root)
    task = kernel.create("local model shared memory", goal="sync graph after local dispatch", risk="low")
    kernel.claim(task["id"], "local-router")
    kernel.start(task["id"])

    def fake_call_llm(self, **kwargs):
        return "done by local model"

    monkeypatch.setattr(
        "memory_os.core.llm_service.DefaultLlmProviderService.call_llm",
        fake_call_llm,
    )

    result = DispatcherEngine(root).local_model(task["id"], "do it", dry_run=False)

    assert result.ok is True
    assert Path(result.evidence_path).exists()

    import sqlite3
    conn = sqlite3.connect(root / "memory" / "memory_os.db")
    try:
        rows = conn.execute(
            "SELECT id, summary FROM graph_nodes WHERE id LIKE 'task:local-model-shared-memory%'"
        ).fetchall()
    finally:
        conn.close()

    assert rows, "task memory node should be synced into SQLite graph_nodes"
    assert "local model shared memory" in rows[0][1].lower()


def test_pre_dispatch_context_hook_and_system_instruction(root, monkeypatch):
    kernel = TaskKernel(root)
    task = kernel.create("hook test task", goal="verify context hook and system instruction", risk="low")
    kernel.claim(task["id"], "test-agent")
    kernel.start(task["id"])

    d = DispatcherEngine(root)

    # 1. Test CLI agent prompt injection
    context_prompt = d._build_cli_context(task["id"], "extra work")
    from memory_os.toolkit.dispatcher import SYSTEM_INSTRUCTION
    assert SYSTEM_INSTRUCTION in context_prompt

    # 2. Test local_model system prompt injection
    captured = {}
    def fake_call_llm(self, **kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(
        "memory_os.core.llm_service.DefaultLlmProviderService.call_llm",
        fake_call_llm,
    )
    res = d.local_model(task["id"], "test local model prompt", system_prompt="Base sys prompt", dry_run=False)
    assert res.ok is True
    assert SYSTEM_INSTRUCTION in captured["system_prompt"]
    assert "Base sys prompt" in captured["system_prompt"]

    # 3. Test evidence records system instruction
    ev_path = Path(res.evidence_path)
    assert ev_path.exists()
    evidence_data = json.loads(ev_path.read_text(encoding="utf-8"))
    assert evidence_data.get("system_instruction") == SYSTEM_INSTRUCTION
    assert "context_pack_built" in evidence_data
