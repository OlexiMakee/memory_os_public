from pathlib import Path
from memory_os.toolkit.workspace_registry import (
    load_workspace_registry,
    save_workspace_registry,
    register_workspace,
    unregister_workspace,
    list_workspaces,
)


def test_workspace_registry_lifecycle(monkeypatch, tmp_path):
    registry_dir = tmp_path / ".memory_os"
    registry_file = registry_dir / "workspaces.toml"
    
    monkeypatch.setattr("memory_os.toolkit.workspace_registry.REGISTRY_DIR", registry_dir)
    monkeypatch.setattr("memory_os.toolkit.workspace_registry.REGISTRY_FILE", registry_file)

    assert list_workspaces() == []

    proj_path = tmp_path / "dev" / "my_project"
    proj_path.mkdir(parents=True)

    slug = register_workspace(proj_path, name="My Project")
    assert slug == "my_project"
    assert registry_file.exists()

    ws_list = list_workspaces()
    assert len(ws_list) == 1
    assert ws_list[0]["name"] == "My Project"
    assert ws_list[0]["path"] == str(proj_path.resolve())

    assert unregister_workspace("my_project") is True
    assert list_workspaces() == []


def test_workspace_registry_slug_collision_and_escaping(monkeypatch, tmp_path):
    registry_dir = tmp_path / ".memory_os"
    registry_file = registry_dir / "workspaces.toml"
    
    monkeypatch.setattr("memory_os.toolkit.workspace_registry.REGISTRY_DIR", registry_dir)
    monkeypatch.setattr("memory_os.toolkit.workspace_registry.REGISTRY_FILE", registry_file)

    proj_a = tmp_path / "dev_a" / "my_project"
    proj_b = tmp_path / "dev_b" / "my_project"
    proj_a.mkdir(parents=True)
    proj_b.mkdir(parents=True)

    slug_a = register_workspace(proj_a, name='Project "Quote"')
    slug_b = register_workspace(proj_b, name='Project "Quote"')

    assert slug_a == "project__quote"
    assert slug_b.startswith("project__quote_")
    assert slug_a != slug_b

    ws_list = list_workspaces()
    assert len(ws_list) == 2


def test_workspace_registry_empty_slug_falls_back(monkeypatch, tmp_path):
    registry_dir = tmp_path / ".memory_os"
    registry_file = registry_dir / "workspaces.toml"

    monkeypatch.setattr("memory_os.toolkit.workspace_registry.REGISTRY_DIR", registry_dir)
    monkeypatch.setattr("memory_os.toolkit.workspace_registry.REGISTRY_FILE", registry_file)

    proj = tmp_path / "dev" / "project"
    proj.mkdir(parents=True)

    slug = register_workspace(proj, name="!!!")

    assert slug == "workspace"
    assert "[workspace.workspace]" in registry_file.read_text(encoding="utf-8")
