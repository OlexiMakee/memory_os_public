import json

from memory_os.toolkit.workspace import send_task


def test_send_task_failure_writes_comm_failed_event(tmp_path, monkeypatch, capsys):
    (tmp_path / "memory_os.config.json").write_text(
        json.dumps({"version": "0.1"}),
        encoding="utf-8",
    )

    def fail_send(*args, **kwargs):
        raise RuntimeError("transport unavailable")

    monkeypatch.setattr("memory_os.toolkit.agent_comm.AgentComm.send", fail_send)

    assert send_task("codex", "task_failure_event", "test failure", root=tmp_path) is False
    assert "transport unavailable" in capsys.readouterr().err

    events_path = tmp_path / "agent_context" / "task_events.jsonl"
    event = json.loads(events_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["event"] == "comm.failed"
    assert event["recipient"] == "codex"
    assert event["task_id"] == "task_failure_event"
