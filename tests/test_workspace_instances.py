import json

from memory_os.core.config import MemoryOSConfig
from memory_os.toolkit.workspace import instances


def test_instances_reports_running_zellij_workspace(tmp_path, monkeypatch):
    (tmp_path / "memory_os.config.json").write_text(
        json.dumps({"tmux_session_name": "memory_os_workspace"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "memory_os.toolkit.workspace_runtime.workspace_runtime_diagnostics",
        lambda spec: {
            "session": spec.session_name,
            "runtimes": {
                "tmux": {"runtime": "tmux", "available": False},
                "zellij": {
                    "runtime": "zellij",
                    "session": spec.session_name,
                    "available": True,
                    "state": "running",
                },
            },
            "zellij_exited_sessions": [],
        },
    )

    expected_session = MemoryOSConfig(str(tmp_path / "memory_os.config.json")).tmux_session_name
    result = instances(tmp_path)

    assert result["workspace"] == {
        "runtime": "zellij",
        "session": expected_session,
        "windows": 1,
        "attached": False,
    }
