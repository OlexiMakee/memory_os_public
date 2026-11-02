from memory_os.toolkit.workspace import _resolve_agent_launch_cmd


def _write_registry(root):
    registry_dir = root / "agent_context" / "agents"
    registry_dir.mkdir(parents=True, exist_ok=True)
    (registry_dir / "registry.toml").write_text(
        """
[agent.codex]
kind = "cli_agent"
command = ["codex"]
launch_flags = ["--sandbox", "danger-full-access", "--ask-for-approval", "never"]
""",
        encoding="utf-8",
    )


def test_full_autonomy_keeps_launch_flags(tmp_path):
    _write_registry(tmp_path)
    cmd = _resolve_agent_launch_cmd("codex", tmp_path, profile="full_autonomy")
    assert "--sandbox" in cmd
    assert "danger-full-access" in cmd


def test_supervised_strips_launch_flags(tmp_path):
    _write_registry(tmp_path)
    cmd = _resolve_agent_launch_cmd("codex", tmp_path, profile="supervised")
    assert "--sandbox" not in cmd
    assert "danger-full-access" not in cmd
    assert "--ask-for-approval" not in cmd
