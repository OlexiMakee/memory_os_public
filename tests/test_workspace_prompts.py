from memory_os.toolkit.workspace_prompts import PRINCIPLE_SENTINEL, PromptPrincipleSync


def test_prompt_principle_sync_updates_only_cli_agents_and_is_idempotent(tmp_path):
    registry_dir = tmp_path / "agent_context" / "agents"
    prompt_dir = registry_dir / "prompts"
    prompt_dir.mkdir(parents=True)
    (registry_dir / "registry.toml").write_text(
        """
[agent.codex]
kind = "cli_agent"
system_prompt_file = "agent_context/agents/prompts/codex.md"

[agent.local]
kind = "local_model"
system_prompt_file = "agent_context/agents/prompts/local.md"
""",
        encoding="utf-8",
    )
    codex_prompt = prompt_dir / "codex.md"
    local_prompt = prompt_dir / "local.md"
    codex_prompt.write_text("[SYSTEM: obsolete]\n\n# Existing rules\nKeep this.\n", encoding="utf-8")
    local_prompt.write_text("local rules\n", encoding="utf-8")

    sync = PromptPrincipleSync(tmp_path)
    assert sync.sync() == [codex_prompt]

    first_content = codex_prompt.read_text(encoding="utf-8")
    assert PRINCIPLE_SENTINEL in first_content
    assert "[SYSTEM: obsolete]" not in first_content
    assert "# Existing rules\nKeep this." in first_content
    assert local_prompt.read_text(encoding="utf-8") == "local rules\n"

    assert sync.sync() == []
    assert codex_prompt.read_text(encoding="utf-8") == first_content
