import argparse

from memory_os.cli import build_parser, cmd_transition
from memory_os.core.config import MemoryOSConfig


def test_transition_parser_exposes_min_confidence():
    parser = build_parser()
    args = parser.parse_args(["transition", "--min-confidence", "0.75"])
    assert args.command == "transition"
    assert args.min_confidence == 0.75
    default_args = parser.parse_args(["transition"])
    assert default_args.min_confidence is None


def test_cmd_transition_forwards_min_confidence(monkeypatch, tmp_path):
    calls = {}

    class DummyLifecycle:
        def __init__(self, config):
            calls["config_root"] = config.root_dir

        def transition(self, validator=None, min_confidence=0.5):
            calls["transition"] = (validator, min_confidence)
            return 0

        def prune(self):
            calls["prune"] = True

        def manifest(self):
            calls["manifest"] = True

    monkeypatch.setattr("memory_os.cli_groups.memory_cmds.LifecycleManager", DummyLifecycle)

    config = MemoryOSConfig(config_path=str(tmp_path / "memory_os.config.json"))
    args = argparse.Namespace(validator="cli-test", min_confidence=0.8, prune=False)

    assert cmd_transition(args, config) == 0
    assert calls["transition"] == ("cli-test", 0.8)
    assert "prune" not in calls
    assert calls["manifest"] is True


def test_cmd_transition_uses_config_confidence_threshold(monkeypatch, tmp_path):
    calls = {}

    class DummyLifecycle:
        def __init__(self, config):
            pass

        def transition(self, validator=None, min_confidence=None):
            calls["transition"] = (validator, min_confidence)
            return 0

        def prune(self):
            calls["prune"] = True

        def manifest(self):
            calls["manifest"] = True

    monkeypatch.setattr("memory_os.cli_groups.memory_cmds.LifecycleManager", DummyLifecycle)

    (tmp_path / "memory_os.config.json").write_text(
        '{"version":"0.1","memory":{"confidence_threshold":0.82}}',
        encoding="utf-8",
    )
    config = MemoryOSConfig(config_path=str(tmp_path / "memory_os.config.json"))
    args = argparse.Namespace(validator="cli-test", min_confidence=None, prune=False)

    assert cmd_transition(args, config) == 0
    assert calls["transition"] == ("cli-test", 0.82)


def test_cmd_transition_prints_status_summary(monkeypatch, tmp_path, capsys):
    class DummyLifecycle:
        def __init__(self, config):
            pass

        def transition(self, validator=None, min_confidence=0.5):
            nodes_dir = tmp_path / "memory"
            nodes_dir.mkdir(parents=True, exist_ok=True)
            (nodes_dir / "nodes.jsonl").write_text(
                "\n".join(
                    [
                        '{"id":"a","status":"verified"}',
                        '{"id":"b","status":"draft"}',
                        '{"id":"c","status":"observed"}',
                        '{"id":"d","status":"superseded"}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            return 0

        def prune(self):
            return 0

        def manifest(self):
            return 0

    monkeypatch.setattr("memory_os.cli_groups.memory_cmds.LifecycleManager", DummyLifecycle)

    config = MemoryOSConfig(config_path=str(tmp_path / "memory_os.config.json"))
    args = argparse.Namespace(validator="cli-test", min_confidence=0.75, prune=False)

    assert cmd_transition(args, config) == 0
    out = capsys.readouterr().out
    assert "Lifecycle transition complete:" in out
    assert "verified=1" in out
    assert "held=2" in out
    assert "superseded=1" in out
    assert "min_confidence=0.75" in out


def test_cmd_memory_write_records_draft_candidate(monkeypatch, tmp_path, capsys):
    import argparse
    import json
    from memory_os.cli import cmd_memory_write
    from memory_os.core.config import MemoryOSConfig

    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    (tmp_path / "memory_os.config.json").write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MEMORY_OS_AGENT_ID", "claude")

    config = MemoryOSConfig(str(tmp_path / "memory_os.config.json"))
    args = argparse.Namespace(
        node_type="fact", summary="test decision recorded", node_id=None,
        evidence="", tags="night,test", confidence=0.8, validator=None,
    )
    assert cmd_memory_write(args, config) == 0
    out = capsys.readouterr().out
    assert "recorded fact:test-decision-recorded-" in out

    nodes = [json.loads(l) for l in (tmp_path / "memory" / "nodes.jsonl").read_text().splitlines()]
    node = nodes[-1]
    assert node["status"] == "draft"
    assert node["confidence"] == 0.8
    assert node["tags"] == ["night", "test"]

    # duplicate id refused
    args2 = argparse.Namespace(
        node_type="fact", summary="test decision recorded", node_id=node["id"],
        evidence="", tags=None, confidence=0.8, validator=None,
    )
    assert cmd_memory_write(args2, config) == 1
