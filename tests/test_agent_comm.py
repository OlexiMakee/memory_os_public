import json
from pathlib import Path

import pytest

from memory_os.toolkit.agent_comm import AgentComm, format_inbox_text, format_resume_report, format_status_text
from memory_os.toolkit.agent_transport import TransportResult
from memory_os.toolkit.task_kernel import TaskKernel


@pytest.fixture
def root(tmp_path):
    (tmp_path / "agent_context" / "agents").mkdir(parents=True)
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context" / "task_events.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory_os.config.json").write_text(
        json.dumps({"version": "0.1"}), encoding="utf-8"
    )
    (tmp_path / "agent_context" / "agents" / "registry.toml").write_text(
        """
[agent.claude]
kind = "cli_agent"
tmux_session = "0"

[agent.codex]
kind = "cli_agent"
tmux_session = "4"

[agent.agy]
kind = "cli_agent"
tmux_session = "2"

[agent.local-router]
kind = "local_model"
tmux_session = "local-router"
""",
        encoding="utf-8",
    )
    return tmp_path


def test_comm_send_unlocks_tmux_logs_event_and_syncs_memory(root, monkeypatch):
    calls = []

    def fake_which(binary):
        return f"/usr/bin/{binary}"

    def fake_run(cmd, **kwargs):
        if "list-panes" not in cmd and "capture-pane" not in cmd:
            calls.append(cmd)
        return __import__("subprocess").CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("memory_os.toolkit.agent_comm.shutil.which", fake_which)
    monkeypatch.setattr("memory_os.toolkit.agent_comm.subprocess.run", fake_run)

    comm = AgentComm(root)
    result = comm.send("claude", "Need review", kind="TASK_ASSIGN", sender="codex", task_id="task_abc123")

    assert result.ok is True
    assert result.tmux_target == "0"
    assert calls[0][-1] == "Escape"
    assert calls[1][-1] == "Enter"
    assert "Need review" in calls[2][-1]
    assert "[SWARM MESSAGE" in calls[2][-1]
    assert calls[3][-1] == "Enter"
    assert len(calls) == 4

    events = [json.loads(line) for line in (root / "agent_context" / "task_events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events[-1]["event"] == "comm.sent"
    assert events[-1]["kind"] == "TASK_ASSIGN"
    assert events[-1]["sender"] == "codex"
    assert events[-1]["recipient"] == "claude"
    assert events[-1]["task_id"] == "task_abc123"
    assert events[-1]["tmux_target"] == "0"

    inbox_path = root / "agent_context" / "inbox" / "claude.jsonl"
    assert inbox_path.exists()
    inbox_records = [json.loads(line) for line in inbox_path.read_text(encoding="utf-8").splitlines()]
    assert inbox_records[-1]["kind"] == "TASK_ASSIGN"
    assert inbox_records[-1]["message"] == "Need review"

    nodes = [json.loads(line) for line in (root / "memory" / "nodes.jsonl").read_text(encoding="utf-8").splitlines()]
    assert nodes[-1]["type"] == "fact"
    assert "Need review" in nodes[-1]["summary"]


def test_comm_send_uses_file_transport_without_tmux(root, monkeypatch):
    monkeypatch.setattr("memory_os.toolkit.agent_comm.shutil.which", lambda _binary: None)
    monkeypatch.setattr(
        "memory_os.core.repository.MemoryRepository.sync_graph_nodes",
        lambda self: None,
    )

    comm = AgentComm(root)
    result = comm.send("codex", "Check inbox transport", kind="TASK_ASSIGN", sender="claude", task_id="task_file001")

    assert result.ok is True
    assert result.transport == "file"
    inbox_path = root / "agent_context" / "inbox" / "codex.jsonl"
    inbox_records = [json.loads(line) for line in inbox_path.read_text(encoding="utf-8").splitlines()]
    assert inbox_records[-1]["message"] == "Check inbox transport"

    events = [json.loads(line) for line in (root / "agent_context" / "task_events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events[-1]["event"] == "comm.sent"
    assert events[-1]["recipient"] == "codex"


def test_comm_send_can_force_file_transport(root, monkeypatch):
    monkeypatch.setenv("MEMORY_OS_AGENT_TRANSPORT", "file")
    monkeypatch.setattr("memory_os.toolkit.agent_comm.shutil.which", lambda _binary: "/usr/bin/tmux")
    monkeypatch.setattr(
        "memory_os.core.repository.MemoryRepository.sync_graph_nodes",
        lambda self: None,
    )

    comm = AgentComm(root)
    result = comm.send("claude", "Use file transport", kind="TASK_ASSIGN", sender="codex", task_id="task_file002")

    assert result.ok is True
    assert result.transport == "file"


def test_comm_memory_sync_uses_user_timezone(root, monkeypatch):
    (root / "memory_os.config.json").write_text(
        json.dumps({"version": "0.1", "user_timezone": "Europe/Kyiv"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("MEMORY_OS_AGENT_TRANSPORT", "file")
    monkeypatch.setattr(
        "memory_os.core.repository.MemoryRepository.sync_graph_nodes",
        lambda self: None,
    )

    result = AgentComm(root).send(
        "claude",
        "timecode probe",
        kind="TASK_ASSIGN",
        sender="codex",
        task_id="task_comm_timecode",
    )

    assert result.ok is True
    nodes = [json.loads(line) for line in (root / "memory" / "nodes.jsonl").read_text(encoding="utf-8").splitlines()]
    # Europe/Kyiv is EET (+02:00 in standard/winter time) or EEST (+03:00 in summer/daylight time)
    assert nodes[-1]["freshness"].endswith(("+02:00", "+03:00"))


def test_comm_send_falls_back_to_inbox_when_tmux_wakeup_fails(root, monkeypatch):
    monkeypatch.setenv("MEMORY_OS_AGENT_TRANSPORT", "tmux")
    monkeypatch.setattr(
        "memory_os.core.repository.MemoryRepository.sync_graph_nodes",
        lambda self: None,
    )

    def broken_send(*_args, **_kwargs):
        raise RuntimeError("tmux wake failed")

    monkeypatch.setattr("memory_os.toolkit.agent_transport.MultiplexerAgentTransport.send_text", broken_send)

    comm = AgentComm(root)
    result = comm.send("agy", "Review memory efficiency", kind="TASK_ASSIGN", sender="codex", task_id="task_inbox_fallback")

    assert result.ok is True
    assert result.error == "tmux wake failed"
    assert result.transport == "tmux:inbox-only"
    inbox_path = root / "agent_context" / "inbox" / "agy.jsonl"
    inbox_records = [json.loads(line) for line in inbox_path.read_text(encoding="utf-8").splitlines()]
    assert inbox_records[-1]["message"] == "Review memory efficiency"


def test_comm_status_report_falls_back_to_inbox_when_tmux_wakeup_fails(root, monkeypatch):
    monkeypatch.setenv("MEMORY_OS_AGENT_TRANSPORT", "tmux")
    monkeypatch.setattr(
        "memory_os.core.repository.MemoryRepository.sync_graph_nodes",
        lambda self: None,
    )

    def broken_send(*_args, **_kwargs):
        raise RuntimeError("zellij wake failed")

    monkeypatch.setattr("memory_os.toolkit.agent_transport.MultiplexerAgentTransport.send_text", broken_send)

    comm = AgentComm(root)
    result = comm.send(
        "claude",
        "done with fallback",
        kind="STATUS_REPORT",
        sender="codex",
        task_id="task_status_fallback",
    )

    assert result.ok is True
    assert result.error == "zellij wake failed"
    assert result.transport == "tmux:inbox-only"
    assert (root / "agent_context" / "done" / "task_status_fallback.json").exists()
    inbox_path = root / "agent_context" / "inbox" / "claude.jsonl"
    inbox_records = [json.loads(line) for line in inbox_path.read_text(encoding="utf-8").splitlines()]
    assert inbox_records[-1]["kind"] == "STATUS_REPORT"
    assert inbox_records[-1]["message"] == "done with fallback"


def test_comm_send_unknown_recipient_is_file_only(root, monkeypatch):
    monkeypatch.setattr(
        "memory_os.core.repository.MemoryRepository.sync_graph_nodes",
        lambda self: None,
    )

    class SpyTransport:
        name = "spy"
        interactive = True

        def __init__(self):
            self.calls = []

        def send_text(self, target, message, *, submit=True, unlock_buffers=True):
            self.calls.append((target, message))
            return TransportResult(ok=True, backend=self.name, target=target)

        def capture_text(self, target, *, lines=80, full_history=False):
            return None

    transport = SpyTransport()
    result = AgentComm(root, transport=transport).send(
        "system",
        "ok",
        kind="STATUS_REPORT",
        sender="codex",
        task_id="task_system_file_only",
    )

    assert result.ok is True
    assert result.tmux_target is None
    assert result.transport == "spy:file-only"
    assert transport.calls == []
    assert (root / "agent_context" / "done" / "task_system_file_only.json").exists()
    events = [
        json.loads(line)
        for line in (root / "agent_context" / "task_events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["event"] == "comm.sent"
    assert not any(event.get("event") == "comm.failed" for event in events)


def test_comm_direct_uses_file_transport_without_tmux(root, monkeypatch):
    monkeypatch.setattr("memory_os.toolkit.agent_comm.shutil.which", lambda _binary: None)
    monkeypatch.setattr(
        "memory_os.core.repository.MemoryRepository.sync_graph_nodes",
        lambda self: None,
    )

    comm = AgentComm(root)
    result = comm.send_direct(
        "agy",
        "[TG_DELIVERY task=task_direct1]: /btw ping",
        sender="telegram",
        task_id="task_direct1",
    )

    assert result.ok is True
    assert result.kind == "DIRECT"
    assert result.transport == "file"
    inbox_path = root / "agent_context" / "inbox" / "agy.jsonl"
    inbox_records = [json.loads(line) for line in inbox_path.read_text(encoding="utf-8").splitlines()]
    assert inbox_records[-1]["kind"] == "DIRECT"
    assert inbox_records[-1]["message"] == "[TG_DELIVERY task=task_direct1]: /btw ping"


def test_comm_direct_falls_back_to_inbox_when_tmux_wakeup_fails(root, monkeypatch):
    monkeypatch.setenv("MEMORY_OS_AGENT_TRANSPORT", "tmux")
    monkeypatch.setattr(
        "memory_os.core.repository.MemoryRepository.sync_graph_nodes",
        lambda self: None,
    )

    def broken_send(*_args, **_kwargs):
        raise RuntimeError("zellij wake failed")

    monkeypatch.setattr("memory_os.toolkit.agent_transport.MultiplexerAgentTransport.send_text", broken_send)

    comm = AgentComm(root)
    result = comm.send_direct(
        "agy",
        "[TG_DELIVERY task=task_direct2]: ping",
        sender="telegram",
        task_id="task_direct2",
    )

    assert result.ok is True
    assert result.kind == "DIRECT"
    assert result.error == "zellij wake failed"
    assert result.transport == "tmux:inbox-only"
    inbox_path = root / "agent_context" / "inbox" / "agy.jsonl"
    inbox_records = [json.loads(line) for line in inbox_path.read_text(encoding="utf-8").splitlines()]
    assert inbox_records[-1]["message"] == "[TG_DELIVERY task=task_direct2]: ping"


def test_comm_inbox_combines_tasks_and_messages(root):
    kernel = TaskKernel(root)
    task = kernel.create("Follow up", goal="Check the patch", risk="medium")
    kernel.claim(task["id"], "codex")
    kernel.start(task["id"])

    inbox_path = root / "agent_context" / "inbox" / "codex.jsonl"
    inbox_path.parent.mkdir(parents=True, exist_ok=True)
    with inbox_path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "ts": "2026-06-28T13:00:00+00:00",
                    "event": "comm.payload",
                    "kind": "TASK_ASSIGN",
                    "sender": "claude",
                    "recipient": "codex",
                    "task_id": task["id"],
                    "message": "Please review the latest patch",
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    inbox = AgentComm(root).inbox("codex", limit=5)

    assert inbox["recipient"] == "codex"
    assert inbox["task_count"] == 1
    assert inbox["message_count"] == 1
    text = format_inbox_text(inbox)
    assert "Tasks" in text
    assert "Messages" in text
    assert task["id"] in text
    assert "Please review the latest patch" in text


def test_comm_status_reports_tmux_targets_and_recent_events(root, monkeypatch):
    monkeypatch.setattr("memory_os.toolkit.agent_comm.shutil.which", lambda _binary: "/usr/bin/tmux")
    monkeypatch.setattr(
        "memory_os.toolkit.agent_comm.subprocess.run",
        lambda *args, **kwargs: __import__("subprocess").CompletedProcess(args[0], 0, stdout="", stderr=""),
    )

    events_path = root / "agent_context" / "task_events.jsonl"
    with events_path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "ts": "2026-06-28T13:05:00+00:00",
                    "event": "comm.sent",
                    "kind": "STATUS_REPORT",
                    "sender": "codex",
                    "recipient": "claude",
                    "message": "ping",
                    "tmux_target": "0",
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    quota_path = root / "agent_context" / "agents" / "quota_monitor_state.json"
    quota_path.write_text(
        json.dumps({"claude": {"has_limit": False, "usage": {"5h": 12, "week": 34}}}),
        encoding="utf-8",
    )

    status = AgentComm(root).status()
    text = format_status_text(status)
    assert status["multiplexer_available"] is True
    assert status["tmux_targets"]["claude"] == "0"
    assert status["tmux_targets"]["codex"] == "4"
    assert status["message_events"] == 1
    assert status["recent_events"][-1]["message"] == "ping"
    assert "tmux_targets" in text
    assert "5h:12% | Week:34%" in text


def test_comm_resume_report_uses_user_timezone_and_recent_status_reports(root, monkeypatch):
    monkeypatch.setenv("MEMORY_OS_USER_TZ", "Europe/Kyiv")
    monkeypatch.setattr("memory_os.toolkit.agent_comm.shutil.which", lambda _binary: None)

    events_path = root / "agent_context" / "task_events.jsonl"
    with events_path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "ts": "2026-06-28T13:05:00+00:00",
                    "event": "comm.sent",
                    "kind": "STATUS_REPORT",
                    "sender": "codex",
                    "recipient": "telegram",
                    "task_id": "task_done1",
                    "message": "files changed: none | pytest: not run",
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    report = AgentComm(root).resume_report(limit=3)
    text = format_resume_report(report)

    assert report["user_timezone"] == "Europe/Kyiv"
    assert report["recent_status_reports"][-1]["task_id"] == "task_done1"
    assert "2026-06-28 16:05:00 EEST" in text
    assert "files changed: none" in text


def test_comm_rejects_long_payload_and_missing_task_id(root):
    comm = AgentComm(root)

    with pytest.raises(ValueError, match="task_id is required"):
        comm.send("claude", "Need review", kind="TASK_ASSIGN", sender="codex", task_id="")

    with pytest.raises(ValueError, match="at most 2000 characters"):
        comm.send("claude", "x" * 2001, kind="STATUS_REPORT", sender="codex", task_id="task_abc123")


def _write_inbox(root, recipient, messages):
    inbox_dir = root / "agent_context" / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    path = inbox_dir / f"{recipient}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        for m in messages:
            fh.write(json.dumps(m) + "\n")


def test_inbox_unread_cursor_advances(root):
    comm = AgentComm(root)
    _write_inbox(root, "codex", [
        {"kind": "DIRECT", "sender": "telegram", "recipient": "codex", "task_id": "t1", "ts": "2026-07-03T10:00:00+00:00", "message": "first"},
        {"kind": "DIRECT", "sender": "telegram", "recipient": "codex", "task_id": "t2", "ts": "2026-07-03T10:01:00+00:00", "message": "second"},
    ])

    first = comm.inbox("codex")
    assert first["message_count"] == 2
    assert [m["message"] for m in first["messages"]] == ["first", "second"]

    # cursor advanced — same call now returns nothing
    second = comm.inbox("codex")
    assert second["message_count"] == 0

    # new message arrives — only it is shown
    _write_inbox(root, "codex", [
        {"kind": "DIRECT", "sender": "telegram", "recipient": "codex", "task_id": "t3", "ts": "2026-07-03T10:02:00+00:00", "message": "third"},
    ])
    third = comm.inbox("codex")
    assert [m["message"] for m in third["messages"]] == ["third"]


def test_inbox_peek_does_not_advance(root):
    comm = AgentComm(root)
    _write_inbox(root, "codex", [
        {"kind": "DIRECT", "sender": "telegram", "recipient": "codex", "task_id": "t1", "ts": "2026-07-03T10:00:00+00:00", "message": "msg"},
    ])
    assert comm.inbox("codex", peek=True)["message_count"] == 1
    assert comm.inbox("codex", peek=True)["message_count"] == 1
    assert comm.inbox("codex")["message_count"] == 1
    assert comm.inbox("codex")["message_count"] == 0


def test_inbox_all_shows_read_messages(root):
    comm = AgentComm(root)
    _write_inbox(root, "codex", [
        {"kind": "DIRECT", "sender": "telegram", "recipient": "codex", "task_id": "t1", "ts": "2026-07-03T10:00:00+00:00", "message": "old"},
    ])
    comm.inbox("codex")  # consume
    assert comm.inbox("codex")["message_count"] == 0
    assert comm.inbox("codex", unread_only=False)["message_count"] == 1


def test_inbox_task_filter_does_not_advance_cursor(root):
    comm = AgentComm(root)
    _write_inbox(root, "codex", [
        {"kind": "DIRECT", "sender": "telegram", "recipient": "codex", "task_id": "t1", "ts": "2026-07-03T10:00:00+00:00", "message": "for t1"},
        {"kind": "DIRECT", "sender": "telegram", "recipient": "codex", "task_id": "t2", "ts": "2026-07-03T10:01:00+00:00", "message": "for t2"},
    ])
    scoped = comm.inbox("codex", task_id="t1")
    assert [m["message"] for m in scoped["messages"]] == ["for t1"]
    # cursor untouched — full unread view still has both
    full = comm.inbox("codex")
    assert full["message_count"] == 2


def test_inbox_limit_truncation_keeps_unshown_unread(root):
    comm = AgentComm(root)
    _write_inbox(root, "codex", [
        {"kind": "DIRECT", "sender": "telegram", "recipient": "codex", "task_id": f"t{i}", "ts": f"2026-07-03T10:0{i}:00+00:00", "message": f"m{i}"}
        for i in range(5)
    ])
    first = comm.inbox("codex", limit=3)
    assert [m["message"] for m in first["messages"]] == ["m0", "m1", "m2"]
    assert first["unread_remaining"] == 2
    second = comm.inbox("codex", limit=3)
    assert [m["message"] for m in second["messages"]] == ["m3", "m4"]


def test_inbox_rewind_resets_cursor(root):
    comm = AgentComm(root)
    _write_inbox(root, "codex", [
        {"kind": "DIRECT", "sender": "telegram", "recipient": "codex", "task_id": "t1", "ts": "2026-07-03T10:00:00+00:00", "message": "msg"},
    ])
    comm.inbox("codex")
    assert comm.inbox("codex")["message_count"] == 0
    comm.reset_inbox_cursor("codex")
    assert comm.inbox("codex")["message_count"] == 1


def test_read_message_returns_full_body(root):
    comm = AgentComm(root)
    _write_inbox(root, "codex", [
        {"kind": "DIRECT", "sender": "telegram", "recipient": "codex", "task_id": "t1", "ts": "2026-07-03T10:00:00+00:00", "message": "long body " * 50},
    ])
    listing = comm.inbox("codex")
    idx = listing["messages"][0]["_idx"]
    msg = comm.read_message("codex", idx)
    assert msg["message"] == "long body " * 50
    assert comm.read_message("codex", 999) is None


def test_feed_new_only_uses_global_cursor(root):
    comm = AgentComm(root)
    events_path = root / "agent_context" / "task_events.jsonl"
    with events_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event": "comm.sent", "kind": "DIRECT", "sender": "a", "recipient": "b", "ts": "2026-07-03T10:00:00+00:00", "message": "e1"}) + "\n")

    assert len(comm.feed(new_only=True)) == 1
    assert len(comm.feed(new_only=True)) == 0

    with events_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event": "comm.sent", "kind": "DIRECT", "sender": "a", "recipient": "b", "ts": "2026-07-03T10:01:00+00:00", "message": "e2"}) + "\n")
    new = comm.feed(new_only=True)
    assert len(new) == 1 and new[0]["message"] == "e2"

    # plain feed unaffected by cursor
    assert len(comm.feed()) == 2


def test_rotate_events_archives_and_rebases_feed_cursor(root):
    comm = AgentComm(root)
    events_path = root / "agent_context" / "task_events.jsonl"
    with events_path.open("a", encoding="utf-8") as fh:
        for i in range(10):
            fh.write(json.dumps({"event": "comm.sent", "kind": "DIRECT", "sender": "a", "recipient": "b", "ts": f"2026-07-03T10:0{i % 10}:00+00:00", "message": f"e{i}"}) + "\n")

    # consume via cursor, then rotate keeping 4
    comm.feed(new_only=True)
    archive = comm.rotate_events(keep=4)
    assert archive is not None and archive.exists()
    assert len(events_path.read_text().splitlines()) == 4
    assert len(archive.read_text().splitlines()) == 6

    # cursor rebased: no events re-shown
    assert comm.feed(new_only=True) == []

    with events_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event": "comm.sent", "kind": "DIRECT", "sender": "a", "recipient": "b", "ts": "2026-07-03T11:00:00+00:00", "message": "fresh"}) + "\n")
    new = comm.feed(new_only=True)
    assert [e["message"] for e in new] == ["fresh"]


def test_rotate_inbox_rebases_unread_cursor(root):
    comm = AgentComm(root)
    _write_inbox(root, "codex", [
        {"kind": "DIRECT", "sender": "t", "recipient": "codex", "task_id": f"t{i}", "ts": f"2026-07-03T10:0{i}:00+00:00", "message": f"m{i}"}
        for i in range(6)
    ])
    # read first 4, cursor at 4; rotate keeping last 3 (drop 3)
    comm.inbox("codex", limit=4)
    archive = comm.rotate_inbox("codex", keep=3)
    assert archive is not None
    # cursor rebased 4-3=1: only m4, m5 unread (m3 was dropped... m3 in archive? dropped=3 → m0,m1,m2 archived; live=m3,m4,m5; cursor=1 → unread m4,m5)
    result = comm.inbox("codex")
    assert [m["message"] for m in result["messages"]] == ["m4", "m5"]


def test_inbox_cursor_clamps_after_truncate_without_resurfacing(root):
    comm = AgentComm(root)
    _write_inbox(root, "codex", [
        {"kind": "DIRECT", "sender": "t", "recipient": "codex", "task_id": f"t{i}", "ts": f"2026-07-03T10:0{i}:00+00:00", "message": f"m{i}"}
        for i in range(5)
    ])
    assert comm.inbox("codex")["message_count"] == 5

    inbox_path = root / "agent_context" / "inbox" / "codex.jsonl"
    live_tail = inbox_path.read_text(encoding="utf-8").splitlines()[-2:]
    inbox_path.write_text("\n".join(live_tail) + "\n", encoding="utf-8")

    assert comm.inbox("codex")["message_count"] == 0
    cursor = json.loads((root / "agent_context" / "inbox" / ".cursor_codex.json").read_text(encoding="utf-8"))
    assert cursor["line"] == 2


def test_inbox_corrupt_cursor_fast_forwards_hot_file(root):
    comm = AgentComm(root)
    _write_inbox(root, "codex", [
        {"kind": "DIRECT", "sender": "t", "recipient": "codex", "task_id": "t1", "ts": "2026-07-03T10:00:00+00:00", "message": "old"}
    ])
    cursor_path = root / "agent_context" / "inbox" / ".cursor_codex.json"
    cursor_path.write_text("{not json", encoding="utf-8")

    assert comm.inbox("codex")["message_count"] == 0
    cursor = json.loads(cursor_path.read_text(encoding="utf-8"))
    assert cursor["line"] == 1


def test_rotate_noop_below_keep(root):
    comm = AgentComm(root)
    assert comm.rotate_events(keep=1000) is None


def test_interactive_prompt_auto_resolve(root, monkeypatch):
    calls = []
    pane_buffer = "Proposing command...\nDo you want to run this command? [y/N]"

    class FakeMultiplexerManager:
        def __init__(self, root_dir):
            self.root = root_dir
        def resolve_pane_target(self, target):
            return "pane_123"
        def capture_pane(self, target, lines=30, full_history=False):
            return pane_buffer
        def send_keys(self, target, keys, submit=True, unlock_buffers=False):
            calls.append(("send_keys", target, keys))
        @staticmethod
        def is_available():
            return True

    monkeypatch.setattr("memory_os.toolkit.agent_comm.shutil.which", lambda _binary: "/usr/bin/tmux")
    monkeypatch.setattr("memory_os.toolkit.multiplexer_manager.MultiplexerManager", FakeMultiplexerManager)
    
    monkeypatch.setattr(
        "memory_os.toolkit.agent_comm.MultiplexerAgentTransport.send_text",
        lambda self, target, message, submit, unlock_buffers: __import__("collections").namedtuple("Result", ["ok", "backend", "error"])(True, "tmux", None)
    )

    comm = AgentComm(root)
    
    prompt = comm.get_interactive_prompt("codex")
    assert prompt is not None
    assert "Do you want to run this command?" in prompt["question"]
    assert prompt["suggested_answers"] == ["y", "n"]

    comm.send("codex", "Run checkout task", kind="TASK_ASSIGN", sender="claude", task_id="task_auto_resolve")
    assert ("send_keys", "pane_123", "y") in calls
