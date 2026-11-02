import argparse
import json
from pathlib import Path
from memory_os.cli import build_parser
from memory_os.core.config import MemoryOSConfig


def test_cmd_workspace_restart_pane(monkeypatch, tmp_path):
    (tmp_path / "memory_os.config.json").write_text(
        json.dumps({"tmux_session_name": "test_session"}),
        encoding="utf-8",
    )
    config = MemoryOSConfig(str(tmp_path / "memory_os.config.json"))

    resolved_targets = []
    shortcuts_sent = []
    keys_sent = []

    class FakeManager:
        def __init__(self, root):
            self.runtime = "tmux"
            self.session_name = "test_session"

        def resolve_pane_target(self, target):
            resolved_targets.append(target)
            return "%5"

        def send_shortcut(self, target, name):
            shortcuts_sent.append((target, name))
            return True

        def send_keys(self, target, message, **kwargs):
            keys_sent.append((target, message))

    monkeypatch.setattr("memory_os.toolkit.multiplexer_manager.MultiplexerManager", FakeManager)
    import time
    monkeypatch.setattr(time, "sleep", lambda sec: None)

    parser = build_parser()
    args = parser.parse_args(["workspace", "restart-pane", "agent-manager"])
    # Set root_dir in config
    config.root_dir = tmp_path

    # Run command
    res = args.func(args, config)

    assert res == 0
    assert resolved_targets == ["agent-manager"]
    assert shortcuts_sent == [
        ("%5", "cancel"),
        ("%5", "escape"),
        ("%5", "cancel"),
        ("%5", "clear"),
    ]
    # Verify keys sent matches sys.executable -m memory_os agent-manager
    assert len(keys_sent) == 1
    assert keys_sent[0][0] == "%5"
    assert "agent-manager" in keys_sent[0][1]
