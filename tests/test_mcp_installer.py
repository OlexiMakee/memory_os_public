"""Unit tests for one-command MCP config installer (Claude Code, Cursor, Codex)."""

from __future__ import annotations

import json
from pathlib import Path

from memory_os.toolkit.mcp_installer import install_mcp_config


def test_install_mcp_claude_creates_and_merges_existing_servers(tmp_path: Path):
    project = tmp_path / "repo"
    project.mkdir()
    existing_cfg = project / ".mcp.json"
    existing_cfg.write_text(
        json.dumps({"mcpServers": {"other-tool": {"command": "npx", "args": ["other"]}}}),
        encoding="utf-8",
    )

    result = install_mcp_config(
        client="claude",
        root=project,
        scope="project",
        python_executable="/usr/bin/python3",
    )

    assert result["ok"] is True
    assert result["action"] == "updated"
    data = json.loads(existing_cfg.read_text(encoding="utf-8"))
    assert "other-tool" in data["mcpServers"]
    assert data["mcpServers"]["memory-os"]["command"] == "/usr/bin/python3"
    assert data["mcpServers"]["memory-os"]["args"][-1] == "mcp"


def test_install_mcp_cursor_dry_run_does_not_write(tmp_path: Path):
    project = tmp_path / "repo"
    project.mkdir()

    result = install_mcp_config(
        client="cursor",
        root=project,
        scope="project",
        dry_run=True,
    )

    assert result["action"] == "dry_run:created"
    assert not (project / ".cursor" / "mcp.json").exists()


def test_install_mcp_codex_toml_creates_and_updates_idempotently(tmp_path: Path):
    project = tmp_path / "repo"
    project.mkdir()

    r1 = install_mcp_config(
        client="codex",
        root=project,
        scope="project",
        python_executable="/bin/python-a",
    )
    assert r1["action"] == "created"
    cfg_path = project / ".codex" / "config.toml"
    assert "[mcp_servers.memory_os]" in cfg_path.read_text(encoding="utf-8")

    # Append unrelated section and re-run to ensure idempotent replacement
    cfg_path.write_text(
        cfg_path.read_text(encoding="utf-8") + "\n[other]\nflag = true\n",
        encoding="utf-8",
    )
    r2 = install_mcp_config(
        client="codex",
        root=project,
        scope="project",
        python_executable="/bin/python-b",
    )
    assert r2["action"] == "updated"
    final_text = cfg_path.read_text(encoding="utf-8")
    assert final_text.count("[mcp_servers.memory_os]") == 1
    assert 'command = "/bin/python-b"' in final_text
    assert "[other]\nflag = true" in final_text
