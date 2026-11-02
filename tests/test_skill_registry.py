import argparse
import json

from memory_os.cli import cmd_skills
from memory_os.core.config import MemoryOSConfig
from memory_os.toolkit.skill_registry import (
    SkillRegistryError,
    discover_skills,
    format_skill_context,
    load_skill,
    sync_skills,
    validate_skills,
)


def _write_config(root):
    (root / "memory_os.config.json").write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    (root / "memory").mkdir(exist_ok=True)


def _write_skill(root, name="memory-curator", description="Curate Memory OS graph quality."):
    skill_dir = root / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"""---
name: {name}
description: {description}
allowed-tools:
  - shell
  - git
---

# {name}

Use deterministic Memory OS commands first.
""",
        encoding="utf-8",
    )
    (skill_dir / "references").mkdir()
    (skill_dir / "references" / "workflow.md").write_text("Reference.", encoding="utf-8")
    return skill_dir


def test_discover_validate_and_format_skill_context(tmp_path):
    _write_skill(tmp_path)

    skills = discover_skills(tmp_path)

    assert [skill.name for skill in skills] == ["memory-curator"]
    assert skills[0].frontmatter.allowed_tools == ["shell", "git"]
    assert validate_skills(tmp_path)["ok"] is True
    assert '<skill name="memory-curator">' in format_skill_context(skills[0])
    full = skills[0].with_resources()
    assert full.resource_files == {"references": ["workflow.md"]}


def test_load_skill_rejects_directory_name_mismatch(tmp_path):
    skill_dir = _write_skill(tmp_path, name="valid-name")
    renamed = skill_dir.parent / "wrong-name"
    skill_dir.rename(renamed)

    try:
        load_skill(renamed)
    except SkillRegistryError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("expected name mismatch rejection")


def test_validate_reports_missing_skill_md(tmp_path):
    (tmp_path / "skills" / "empty").mkdir(parents=True)

    report = validate_skills(tmp_path)

    assert report["ok"] is False
    assert "missing SKILL.md" in report["errors"][0]


def test_sync_skills_copies_to_agent_targets_and_writes_lock(tmp_path):
    _write_config(tmp_path)
    _write_skill(tmp_path)

    report = sync_skills(tmp_path, agents=["codex", "claude"])

    assert report["ok"] is True
    assert (tmp_path / ".codex" / "skills" / "memory-curator" / "SKILL.md").exists()
    assert (tmp_path / ".claude" / "skills" / "memory-curator" / "SKILL.md").exists()
    lock = json.loads((tmp_path / "memory" / "skills.lock.json").read_text(encoding="utf-8"))
    assert lock["version"] == 1
    assert "memory-curator" in lock["skills"]
    assert lock["skills"]["memory-curator"]["source"] == "skills/memory-curator"
    assert len(lock["skills"]["memory-curator"]["synced_agent_dirs"]) == 2


def test_write_skills_lock(tmp_path):
    from memory_os.toolkit.skill_registry import write_skills_lock
    _write_config(tmp_path)
    _write_skill(tmp_path)

    # Mock sync to set synced dirs in existing lock
    sync_skills(tmp_path, agents=["codex"])

    # Run lock
    res = write_skills_lock(tmp_path)
    assert res["ok"] is True
    assert "memory-curator" in res["skills"]
    assert len(res["skills"]["memory-curator"]["synced_agent_dirs"]) == 1
    assert res["skills"]["memory-curator"]["synced_agent_dirs"][0] == ".codex/skills/memory-curator"

    # Verify written file structure
    lock = json.loads((tmp_path / "memory" / "skills.lock.json").read_text(encoding="utf-8"))
    assert lock["version"] == 1
    assert lock["skills"]["memory-curator"]["source"] == "skills/memory-curator"


def test_sync_skills_replaces_stale_managed_destination(tmp_path):
    _write_config(tmp_path)
    _write_skill(tmp_path)
    stale = tmp_path / ".codex" / "skills" / "memory-curator" / "old.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text("old", encoding="utf-8")

    report = sync_skills(tmp_path, agents=["codex"])

    assert report["ok"] is True
    assert not stale.exists()
    assert (stale.parent / "SKILL.md").exists()


def test_sync_skills_dry_run_does_not_write(tmp_path):
    _write_config(tmp_path)
    _write_skill(tmp_path)

    report = sync_skills(tmp_path, agents=["agy"], dry_run=True)

    assert report["ok"] is True
    assert report["actions"][0]["status"] == "would_sync"
    assert not (tmp_path / ".gemini").exists()
    assert not (tmp_path / "memory" / "skills.lock.json").exists()


def test_sync_skills_injects_into_agents_md(tmp_path):
    _write_config(tmp_path)
    _write_skill(tmp_path)
    
    # Create agents.md file
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text("Some human-authored rules.\n", encoding="utf-8")
    
    report = sync_skills(tmp_path, agents=["codex"])
    assert report["ok"] is True
    
    # Verify block is appended
    content = agents_md.read_text(encoding="utf-8")
    assert "MEMORY_OS SKILLS BLOCK START" in content
    assert "memory-curator" in content
    assert "Some human-authored rules." in content
    
    # Modify skills and verify block is updated idempotently
    skill_dir = tmp_path / "skills" / "memory-curator"
    (skill_dir / "SKILL.md").write_text("""---
name: memory-curator
description: Overwritten description
---
Body""", encoding="utf-8")
    
    report2 = sync_skills(tmp_path, agents=["codex"])
    assert report2["ok"] is True
    content2 = agents_md.read_text(encoding="utf-8")
    assert "Overwritten description" in content2
    # Ensure no duplicate blocks
    assert content2.count("MEMORY_OS SKILLS BLOCK START") == 1


def test_validate_commands_and_mcp(tmp_path):
    import pytest
    from memory_os.toolkit.skill_registry import SkillRegistryError, catalog_resources
    
    _write_config(tmp_path)
    _write_skill(tmp_path)
    
    skill_dir = tmp_path / "skills" / "memory-curator"
    
    # 1. Invalid command file (not .md)
    cmd_dir = skill_dir / "commands"
    cmd_dir.mkdir(parents=True, exist_ok=True)
    (cmd_dir / "bad.txt").write_text("not md", encoding="utf-8")
    with pytest.raises(SkillRegistryError, match="must be a markdown file"):
        load_skill(skill_dir)
        
    (cmd_dir / "bad.txt").unlink()
    (cmd_dir / "good.md").write_text("valid command md", encoding="utf-8")
    # Should load fine now
    spec = load_skill(skill_dir)
    assert "commands" in catalog_resources(skill_dir)
    
    # 2. Invalid MCP file (not .json)
    mcp_dir = skill_dir / "mcp"
    mcp_dir.mkdir(parents=True, exist_ok=True)
    (mcp_dir / "bad.txt").write_text("not json", encoding="utf-8")
    with pytest.raises(SkillRegistryError, match="must be a JSON file"):
        load_skill(skill_dir)
        
    (mcp_dir / "bad.txt").unlink()
    # Invalid JSON syntax
    (mcp_dir / "bad.json").write_text("{invalid json", encoding="utf-8")
    with pytest.raises(SkillRegistryError, match="is not valid JSON"):
        load_skill(skill_dir)
        
    (mcp_dir / "bad.json").write_text('{"name": "mcp-server"}', encoding="utf-8")
    spec2 = load_skill(skill_dir)
    assert "mcp" in catalog_resources(skill_dir)


def test_cmd_skills_validate_json(tmp_path, capsys):
    _write_config(tmp_path)
    _write_skill(tmp_path)
    args = argparse.Namespace(
        root=str(tmp_path),
        skills_action="validate",
        skills_dir="skills",
        format="json",
    )

    code = cmd_skills(args, MemoryOSConfig(str(tmp_path / "memory_os.config.json")))
    out = json.loads(capsys.readouterr().out)

    assert code == 0
    assert out["ok"] is True
    assert out["skills"][0]["frontmatter"]["name"] == "memory-curator"


def test_refresh_skill(tmp_path):
    import subprocess
    from memory_os.toolkit.skill_registry import refresh_skill, load_skill
    
    # 1. Create a local git repository to act as the remote
    git_remote = tmp_path / "git_remote"
    git_remote.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=git_remote, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=git_remote, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=git_remote, check=True)
    
    # Commit dummy skill to remote
    skill_md_content = """---
name: remote-skill
description: Remote sourced test skill
---
# Instructions
Run mock command."""
    (git_remote / "SKILL.md").write_text(skill_md_content, encoding="utf-8")
    subprocess.run(["git", "add", "SKILL.md"], cwd=git_remote, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=git_remote, check=True, capture_output=True)
    
    # Get the commit SHA
    res_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=git_remote, check=True, capture_output=True, text=True)
    expected_sha = res_sha.stdout.strip()
    
    # 2. Setup local workspace in tmp_path
    _write_config(tmp_path)
    local_skill_dir = tmp_path / "skills" / "remote-skill"
    local_skill_dir.mkdir(parents=True, exist_ok=True)
    
    # Write SOURCE.toml
    source_toml_content = f"""
repo = "{git_remote.as_posix()}"
ref = "main"
subdir = ""
"""
    (local_skill_dir / "SOURCE.toml").write_text(source_toml_content, encoding="utf-8")
    
    # Write a temporary/mock SKILL.md that will be overwritten
    (local_skill_dir / "SKILL.md").write_text("old text", encoding="utf-8")
    
    # 3. Execute refresh
    res = refresh_skill(tmp_path, "remote-skill")
    assert res["ok"] is True
    assert res["resolved_ref"] == expected_sha
    
    # Assert SKILL.md was overwritten with remote content
    assert (local_skill_dir / "SKILL.md").read_text(encoding="utf-8") == skill_md_content
    # Assert SOURCE.toml was preserved
    assert "repo =" in (local_skill_dir / "SOURCE.toml").read_text(encoding="utf-8")
    
    # Assert lockfile recorded the resolved_ref
    lock = json.loads((tmp_path / "memory" / "skills.lock.json").read_text(encoding="utf-8"))
    assert lock["skills"]["remote-skill"]["resolved_ref"] == expected_sha
    
    # Verify load_skill now returns remote_source
    spec = load_skill(local_skill_dir)
    assert spec.remote_source is not None
    assert spec.remote_source["repo"] == git_remote.as_posix()


def test_refresh_skill_missing_source(tmp_path):
    import pytest
    from memory_os.toolkit.skill_registry import refresh_skill, SkillRegistryError
    _write_config(tmp_path)
    local_skill_dir = tmp_path / "skills" / "local-only"
    local_skill_dir.mkdir(parents=True, exist_ok=True)
    (local_skill_dir / "SKILL.md").write_text("local skill", encoding="utf-8")
    
    with pytest.raises(SkillRegistryError, match="SOURCE.toml absent"):
        refresh_skill(tmp_path, "local-only")

