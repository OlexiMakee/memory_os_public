import argparse
from pathlib import Path
from memory_os.cli import build_parser, cmd_tmux
from memory_os.core.config import MemoryOSConfig


def test_tmux_press_parser():
    parser = build_parser()
    args = parser.parse_args(["tmux", "press", "claude", "up", "down", "enter"])
    assert args.command == "tmux"
    assert args.tmux_action == "press"
    assert args.target == "claude"
    assert args.keys == ["up", "down", "enter"]


def test_cmd_tmux_press(monkeypatch, tmp_path):
    calls = []

    class DummyMultiplexerManager:
        def __init__(self, root):
            self.root = root
        def send_key_sequence(self, target, keys):
            calls.append((target, keys))

    monkeypatch.setattr("memory_os.toolkit.multiplexer_manager.MultiplexerManager", DummyMultiplexerManager)

    config = MemoryOSConfig(config_path=str(tmp_path / "memory_os.config.json"))
    args = argparse.Namespace(
        root=str(tmp_path),
        tmux_action="press",
        target="claude",
        keys=["up", "down", "enter"]
    )

    assert cmd_tmux(args, config) == 0
    assert calls == [("claude", ["up", "down", "enter"])]
