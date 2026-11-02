import json
import os
import time
from types import SimpleNamespace
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from memory_os.core.config import MemoryOSConfig
from memory_os.adapters.telegram_adapter import TelegramAdapter
from memory_os.adapters.telegram_polling import TelegramPollingDaemon
from memory_os.agent_brain.types import ActionResult


def test_telegram_adapter_parse_update():
    adapter = TelegramAdapter(token="test_token")
    raw = {
        "update_id": 100,
        "message": {
            "message_id": 1,
            "from": {"id": 12345, "username": "oleksii"},
            "chat": {"id": 67890, "type": "private"},
            "text": "Hello bot",
        },
    }
    parsed = adapter.parse_update(raw)
    assert parsed["update_id"] == 100
    assert parsed["chat_id"] == 67890
    assert parsed["text"] == "Hello bot"
    assert parsed["username"] == "oleksii"


def test_telegram_polling_daemon_process_update(tmp_path, monkeypatch):
    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    config = MemoryOSConfig(config_path=str(cfg_path))

    daemon = TelegramPollingDaemon(config, track_tasks=True)

    fake_send = MagicMock(return_value={"ok": True, "result": {}})
    monkeypatch.setattr(daemon.telegram, "send_message", fake_send)

    fake_run = MagicMock(return_value=ActionResult(action="chat", ok=True, data={"reply": "ok"}, action_args={"query": "Привіт"}))
    monkeypatch.setattr(daemon.orchestrator, "run", fake_run)

    fake_respond = MagicMock(return_value="Привіт, чим можу допомогти?")
    monkeypatch.setattr(daemon.responder, "respond", fake_respond)

    raw_update = {
        "update_id": 200,
        "message": {
            "message_id": 2,
            "from": {"id": 111, "username": "tester"},
            "chat": {"id": 222, "type": "private"},
            "text": "Привіт",
        },
    }

    daemon.process_update(raw_update)

    assert fake_run.called
    assert fake_respond.called
    assert fake_send.called
    assert fake_send.call_args[0][0] == 222
    assert "Привіт" in fake_send.call_args[0][1]

    log_file = tmp_path / "agent_context" / "telegram_conversations.jsonl"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    record = json.loads(content)
    assert record["schema_version"] == 1
    assert record["source"] == "telegram"
    assert record["user_text"] == "Привіт"
    assert record["action"] == "chat"
    assert record["action_args"] == {"query": "Привіт"}
    assert record["chat_ref"]
    assert record["user_ref"]
    assert "chat_id" not in record
    assert "username" not in record
    assert "tester" not in content


def test_telegram_polling_daemon_loop_once(tmp_path, monkeypatch):
    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    config = MemoryOSConfig(config_path=str(cfg_path))

    daemon = TelegramPollingDaemon(config, track_tasks=False)

    fake_updates = {
        "ok": True,
        "result": [
            {
                "update_id": 300,
                "message": {
                    "message_id": 3,
                    "from": {"id": 333, "username": "test_user"},
                    "chat": {"id": 444, "type": "private"},
                    "text": "test loop",
                },
            }
        ],
    }

    monkeypatch.setattr(daemon.telegram, "get_updates", lambda offset, limit: {"updates": fake_updates["result"]})
    monkeypatch.setattr(daemon.telegram, "send_message", lambda chat_id, text: {"ok": True})
    monkeypatch.setattr(daemon.orchestrator, "run", lambda text: ActionResult(action="chat", ok=True, data=None))
    monkeypatch.setattr(daemon.responder, "respond", lambda text, res: "Loop reply")

    daemon.run(once=True)
    assert daemon._offset == 301


def test_telegram_swarm_control_rejects_unauthorized_chat(tmp_path, monkeypatch):
    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    config = MemoryOSConfig(config_path=str(cfg_path))
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "999")
    daemon = TelegramPollingDaemon(config, track_tasks=False, swarm_control=True)
    sent = []
    monkeypatch.setattr(daemon.telegram, "send_message", lambda chat_id, text: sent.append((chat_id, text)) or {"ok": True})

    daemon.process_update({
        "update_id": 400,
        "message": {
            "message_id": 4,
            "from": {"id": 111, "username": "tester"},
            "chat": {"id": 222, "type": "private"},
            "text": "/task codex run tests",
        },
    })

    assert sent == [(222, "Unauthorized chat. Configure TELEGRAM_ALLOWED_CHAT_IDS in this project .env.")]


def test_telegram_swarm_control_dispatches_task_to_agent(tmp_path, monkeypatch):
    import threading as _threading

    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    config = MemoryOSConfig(config_path=str(cfg_path))
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "222")
    sent_messages = []
    comm_calls = []
    done_event = _threading.Event()

    def fake_send(self, recipient, message, kind, sender, task_id, **kwargs):
        comm_calls.append({
            "recipient": recipient,
            "message": message,
            "kind": kind,
            "sender": sender,
            "task_id": task_id,
        })
        return SimpleNamespace(ok=True, error=None)

    monkeypatch.setattr("memory_os.toolkit.agent_comm.AgentComm.send", fake_send)
    # AgentStateMonitor.watch returns STUCK (single named agent) → leaves task as "running", no block
    monkeypatch.setattr(
        "memory_os.toolkit.agent_state_monitor.AgentStateMonitor.watch",
        lambda self: ("stuck", {"stuck_sec": 90.0, "idle_sec": 90.0, "agent": "agy"}),
    )
    monkeypatch.setattr(
        "memory_os.toolkit.agent_state_monitor.AgentStateMonitor.capture_baseline",
        lambda self: None,
    )

    def sync_thread(target=None, daemon=None, **kw):
        class _T:
            def start(self):
                target()
                done_event.set()
        return _T()
    monkeypatch.setattr(_threading, "Thread", sync_thread)

    daemon = TelegramPollingDaemon(config, track_tasks=False, swarm_control=True, swarm_watch_timeout=0)
    monkeypatch.setattr(daemon.telegram, "send_message", lambda chat_id, text: sent_messages.append((chat_id, text)) or {"ok": True})

    daemon.process_update({
        "update_id": 401,
        "message": {
            "message_id": 5,
            "from": {"id": 111, "username": "tester"},
            "chat": {"id": 222, "type": "private"},
            "text": "/task agy implement feature",
        },
    })

    done_event.wait(timeout=5)
    assert comm_calls
    assert comm_calls[0]["recipient"] == "agy"
    assert comm_calls[0]["kind"] == "TASK_ASSIGN"
    assert comm_calls[0]["sender"] == "telegram"
    assert "implement feature" in comm_calls[0]["message"]
    assert "[TELEGRAM task=" in comm_calls[0]["message"]
    tasks = json.loads((tmp_path / "agent_context" / "tasks.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert tasks["agent"] == "agy"
    # STUCK on single named agent → leaves task as "running" (pending for late STATUS_REPORT)
    assert tasks["status"] == "running"


def test_telegram_swarm_control_relays_status_report(tmp_path, monkeypatch):
    import threading as _threading

    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    config = MemoryOSConfig(config_path=str(cfg_path))
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "222")
    sent_messages = []
    done_event = _threading.Event()

    monkeypatch.setattr(
        "memory_os.toolkit.agent_comm.AgentComm.send",
        lambda self, recipient, message, kind, sender, task_id, **kwargs: SimpleNamespace(ok=True, error=None),
    )
    # AgentStateMonitor.watch returns DONE with the agent's message
    monkeypatch.setattr(
        "memory_os.toolkit.agent_state_monitor.AgentStateMonitor.watch",
        lambda self: ("done", {"task_id": self.task_id, "sender": "codex", "message": "done | pytest passed"}),
    )
    monkeypatch.setattr(
        "memory_os.toolkit.agent_state_monitor.AgentStateMonitor.capture_baseline",
        lambda self: None,
    )

    def sync_thread(target=None, daemon=None, **kw):
        class _T:
            def start(self):
                target()
                done_event.set()
        return _T()
    monkeypatch.setattr(_threading, "Thread", sync_thread)

    daemon = TelegramPollingDaemon(config, track_tasks=False, swarm_control=True, swarm_watch_timeout=1)
    monkeypatch.setattr(daemon.telegram, "send_message", lambda chat_id, text: sent_messages.append((chat_id, text)) or {"ok": True})

    daemon.process_update({
        "update_id": 403,
        "message": {
            "message_id": 7,
            "from": {"id": 111, "username": "tester"},
            "chat": {"id": 222, "type": "private"},
            "text": "/task codex verify build",
        },
    })

    done_event.wait(timeout=5)
    assert any("done | pytest passed" in t for _, t in sent_messages)


def test_telegram_swarm_control_search_command(tmp_path, monkeypatch):
    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    config = MemoryOSConfig(config_path=str(cfg_path))
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "222")
    sent = []
    monkeypatch.setattr(
        "memory_os.modules.search.MemorySearcher.search_memory",
        lambda self, query, depth=1: [{"id": "n1", "summary": f"match for {query}"}],
    )
    daemon = TelegramPollingDaemon(config, track_tasks=False, swarm_control=True)
    monkeypatch.setattr(daemon.telegram, "send_message", lambda chat_id, text: sent.append((chat_id, text)) or {"ok": True})

    daemon.process_update({
        "update_id": 402,
        "message": {
            "message_id": 6,
            "from": {"id": 111, "username": "tester"},
            "chat": {"id": 222, "type": "private"},
            "text": "/search daemon IPC",
        },
    })

    assert sent == [(222, "Found 1 match(es):\n- n1: match for daemon IPC")]


def test_telegram_swarm_control_resume_command(tmp_path, monkeypatch):
    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    config = MemoryOSConfig(config_path=str(cfg_path))
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "222")
    sent = []

    daemon = TelegramPollingDaemon(config, track_tasks=False, swarm_control=True)
    monkeypatch.setattr(daemon, "_resume_text", lambda limit=5: f"resume limit={limit}")
    monkeypatch.setattr(daemon.telegram, "send_message", lambda chat_id, text: sent.append((chat_id, text)) or {"ok": True})

    daemon.process_update({
        "update_id": 403,
        "message": {
            "message_id": 7,
            "from": {"id": 111, "username": "tester"},
            "chat": {"id": 222, "type": "private"},
            "text": "/resume 3",
        },
    })

    assert sent == [(222, "resume limit=3")]


def test_explicit_agent_prompt_persists_for_next_plain_message(tmp_path, monkeypatch):
    import threading as _threading

    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    config = MemoryOSConfig(config_path=str(cfg_path))
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "222")
    direct_calls = []
    done_event = _threading.Event()
    runs = [0]

    def fake_send_direct(self, recipient, message, sender="telegram", task_id=None, **kwargs):
        direct_calls.append({"recipient": recipient, "message": message, "task_id": task_id})
        return SimpleNamespace(ok=True, error=None)

    monkeypatch.setattr("memory_os.toolkit.agent_comm.AgentComm.send_direct", fake_send_direct)
    monkeypatch.setattr(
        "memory_os.toolkit.agent_state_monitor.AgentStateMonitor.watch",
        lambda self: ("stuck", {"stuck_sec": 90.0, "idle_sec": 90.0, "agent": self.agent_id}),
    )
    monkeypatch.setattr(
        "memory_os.toolkit.agent_state_monitor.AgentStateMonitor.capture_baseline",
        lambda self: None,
    )

    def sync_thread(target=None, daemon=None, **kw):
        class _T:
            def start(self):
                target()
                runs[0] += 1
                if runs[0] == 2:
                    done_event.set()
        return _T()

    monkeypatch.setattr(_threading, "Thread", sync_thread)

    daemon = TelegramPollingDaemon(config, track_tasks=False, swarm_control=True, swarm_watch_timeout=0)
    monkeypatch.setattr(daemon.telegram, "send_message", lambda chat_id, text: {"ok": True})

    daemon.process_update({
        "update_id": 405,
        "message": {
            "message_id": 9,
            "from": {"id": 111, "username": "tester"},
            "chat": {"id": 222, "type": "private"},
            "text": "/codex перший запит",
        },
    })
    daemon.process_update({
        "update_id": 406,
        "message": {
            "message_id": 10,
            "from": {"id": 111, "username": "tester"},
            "chat": {"id": 222, "type": "private"},
            "text": "другий запит без тегу",
        },
    })

    done_event.wait(timeout=5)
    assert daemon._session_agent[222] == "codex"
    assert [call["recipient"] for call in direct_calls] == ["codex", "codex"]
    assert "перший запит" in direct_calls[0]["message"]
    assert "другий запит без тегу" in direct_calls[1]["message"]


def test_telegram_swarm_control_btw_routes_to_last_active_agent(tmp_path, monkeypatch):
    """/btw is a transparent passthrough — direct delivery, no SWARM wrapper, full text preserved."""
    import threading as _threading

    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    config = MemoryOSConfig(config_path=str(cfg_path))
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "222")
    sent_messages = []
    transport_calls = []
    done_event = _threading.Event()

    def fake_send_text(self, target, message, submit=True, unlock_buffers=True):
        from memory_os.toolkit.agent_transport import TransportResult

        transport_calls.append({"target": target, "message": message})
        return TransportResult(ok=True, backend="tmux", target=target)

    monkeypatch.setattr("memory_os.toolkit.agent_comm.shutil.which", lambda _binary: "/usr/bin/tmux")
    monkeypatch.setattr("memory_os.toolkit.agent_transport.MultiplexerAgentTransport.send_text", fake_send_text)
    # Monitor returns STUCK immediately (single agent, direct mode → leaves pending)
    monkeypatch.setattr(
        "memory_os.toolkit.agent_state_monitor.AgentStateMonitor.watch",
        lambda self: ("stuck", {"stuck_sec": 90.0, "idle_sec": 90.0, "agent": "agy"}),
    )
    monkeypatch.setattr(
        "memory_os.toolkit.agent_state_monitor.AgentStateMonitor.capture_baseline",
        lambda self: None,
    )

    def sync_thread(target=None, daemon=None, **kw):
        class _T:
            def start(self):
                target()
                done_event.set()
        return _T()

    monkeypatch.setattr(_threading, "Thread", sync_thread)

    daemon = TelegramPollingDaemon(config, track_tasks=False, swarm_control=True, swarm_watch_timeout=0)
    daemon._session_agent[222] = "agy"
    monkeypatch.setattr(daemon.telegram, "send_message", lambda chat_id, text: sent_messages.append((chat_id, text)) or {"ok": True})

    daemon.process_update({
        "update_id": 404,
        "message": {
            "message_id": 8,
            "from": {"id": 111, "username": "tester"},
            "chat": {"id": 222, "type": "private"},
            "text": "/btw перевір це",
        },
    })

    done_event.wait(timeout=5)
    # direct delivery uses the configured transport, NOT AgentComm.send(TASK_ASSIGN)
    assert transport_calls, "expected transport to be called for direct delivery"
    # full text including /btw prefix delivered unchanged
    assert "/btw перевір це" in transport_calls[0]["message"]
    # simple direct delivery sentinel, not [SWARM MESSAGE] wrapper
    assert "[TG_DELIVERY task=task_" in transport_calls[0]["message"]
    assert "[SWARM MESSAGE" not in transport_calls[0]["message"]

    task_id = next(iter(daemon._swarm_pending_tasks))
    assert task_id not in daemon._relayed_done_tasks
    done_dir = tmp_path / "agent_context" / "done"
    done_dir.mkdir(parents=True, exist_ok=True)
    (done_dir / f"{task_id}.json").write_text(
        json.dumps({"task_id": task_id, "sender": "agy", "message": "пізня відповідь"}),
        encoding="utf-8",
    )

    daemon._check_and_relay_done_tasks()

    assert any("пізня відповідь" in text for _, text in sent_messages)
    loop_records = [
        json.loads(line)
        for line in (tmp_path / "agent_context" / "loops.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(
        rec.get("event") == "loop.verifier_result"
        and rec.get("verifier") == "telegram_async_relay"
        and rec.get("verdict") == "pass"
        for rec in loop_records
    )


def test_telegram_async_relay_keeps_pending_when_send_message_fails(tmp_path, monkeypatch):
    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    config = MemoryOSConfig(config_path=str(cfg_path))
    daemon = TelegramPollingDaemon(config, track_tasks=False, swarm_control=True, swarm_watch_timeout=0)
    monkeypatch.setattr(
        daemon.telegram,
        "send_message",
        lambda chat_id, text: {"ok": False, "detail": "simulated telegram failure"},
    )

    task_id = "task_failed_telegram_relay"
    daemon._swarm_pending_tasks[task_id] = {
        "chat_id": 222,
        "prompt": "test",
        "ts": time.time(),
        "dedup_key": "codex:test",
        "agent_id": "codex",
        "attempt_id": None,
        "worktree_path": None,
        "baseline_commit": None,
    }
    done_dir = tmp_path / "agent_context" / "done"
    done_dir.mkdir(parents=True, exist_ok=True)
    (done_dir / f"{task_id}.json").write_text(
        json.dumps({"task_id": task_id, "sender": "codex", "message": "not delivered"}),
        encoding="utf-8",
    )

    daemon._check_and_relay_done_tasks()

    assert task_id in daemon._swarm_pending_tasks
    assert task_id not in daemon._relayed_done_tasks
    events = [
        json.loads(line)
        for line in (tmp_path / "agent_context" / "task_events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(e.get("event") == "telegram.done_relay_failed" and e.get("task_id") == task_id for e in events)


def test_telegram_async_relay_status_updates(tmp_path, monkeypatch):
    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    config = MemoryOSConfig(config_path=str(cfg_path))
    daemon = TelegramPollingDaemon(config, track_tasks=False, swarm_control=True, swarm_watch_timeout=0)

    sent_messages = []
    monkeypatch.setattr(daemon, "_send_text", lambda chat_id, text: sent_messages.append(text) or True)

    task_id = "task_status_updates"
    now = time.time()
    daemon._swarm_pending_tasks[task_id] = {
        "chat_id": 222,
        "prompt": "test",
        "ts": now - 70.0,  # 70s ago
        "dedup_key": "codex:test",
        "agent_id": "codex",
        "attempt_id": None,
        "worktree_path": None,
        "baseline_commit": None,
        "last_notified_at": now - 70.0,
    }

    # Case 1: Status update sent at 60s
    daemon._check_and_relay_done_tasks()
    assert len(sent_messages) == 1
    assert "в процесі виконання" in sent_messages[0] or "виявлено помилку" in sent_messages[0] or "заблокована" in sent_messages[0]
    assert task_id in daemon._swarm_pending_tasks

    # Case 2: Timeout at 600s
    daemon._swarm_pending_tasks[task_id]["ts"] = now - 650.0
    daemon._swarm_pending_tasks[task_id]["last_notified_at"] = now - 70.0
    sent_messages.clear()
    daemon._check_and_relay_done_tasks()
    assert len(sent_messages) == 1
    assert "перевищила ліміт часу" in sent_messages[0]
    assert task_id not in daemon._swarm_pending_tasks


def test_telegram_daemon_control_start_writes_pid_and_uses_detached_command(tmp_path, monkeypatch, capsys):
    import argparse

    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    config = MemoryOSConfig(config_path=str(cfg_path))
    popen_calls = []

    class FakeProcess:
        pid = 4242

    def fake_popen(cmd, **kwargs):
        popen_calls.append({"cmd": cmd, "kwargs": kwargs})
        return FakeProcess()

    monkeypatch.setattr("memory_os.cli_groups.telegram_cmds._discover_telegram_daemon_pids", lambda root: [])
    monkeypatch.setattr("memory_os.cli_groups.telegram_cmds.subprocess.Popen", fake_popen)

    from memory_os.cli import cmd_telegram_daemon_control

    args = argparse.Namespace(
        telegram_daemon_action="start",
        poll_interval=1.5,
        swarm_watch_timeout=0,
        no_task_tracking=False,
        force=False,
    )
    code = cmd_telegram_daemon_control(args, config)
    out = capsys.readouterr().out

    assert code == 0
    assert "Telegram daemon started (PID 4242)" in out
    assert (tmp_path / "data" / "telegram-daemon.pid").read_text(encoding="utf-8").strip() == "4242"
    cmd = popen_calls[0]["cmd"]
    start = cmd.index("telegram-daemon")
    assert cmd[start:start + 6] == [
        "telegram-daemon",
        "--swarm-control",
        "--swarm-watch-timeout",
        "0",
        "--poll-interval",
        "1.5",
    ]
    assert popen_calls[0]["kwargs"]["cwd"] == str(tmp_path)
    assert popen_calls[0]["kwargs"]["start_new_session"] is True


def test_telegram_daemon_control_stop_force_removes_pid_file(tmp_path, monkeypatch, capsys):
    import argparse
    import signal

    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    pid_file = tmp_path / "data" / "telegram-daemon.pid"
    pid_file.parent.mkdir()
    pid_file.write_text("4242\n", encoding="utf-8")
    config = MemoryOSConfig(config_path=str(cfg_path))
    signals = []
    monotonic_values = iter([0.0, 4.0])

    monkeypatch.setattr("memory_os.cli_groups.telegram_cmds._is_pid_alive", lambda pid: True)
    monkeypatch.setattr("memory_os.cli_groups.telegram_cmds._pid_is_telegram_daemon", lambda pid, root: True)
    monkeypatch.setattr("memory_os.cli_groups.telegram_cmds.os.kill", lambda pid, sig: signals.append((pid, sig)))
    monkeypatch.setattr("time.monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    from memory_os.cli import cmd_telegram_daemon_control

    args = argparse.Namespace(
        telegram_daemon_action="stop",
        poll_interval=2.0,
        swarm_watch_timeout=0,
        no_task_tracking=False,
        force=True,
    )
    code = cmd_telegram_daemon_control(args, config)
    out = capsys.readouterr().out

    assert code == 0
    assert "Telegram daemon killed (PID 4242)" in out
    assert signals[0] == (4242, signal.SIGTERM)
    assert signals[-1] == (4242, signal.SIGKILL)
    assert not pid_file.exists()


def test_dispatch_with_failover_on_self_reported_rate_limit(tmp_path, monkeypatch):
    """Auto-dispatch: first agent self-reports quota_exhausted in STATUS_REPORT → failover to second."""
    import threading as _threading

    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    registry_dir = tmp_path / "agent_context" / "agents"
    registry_dir.mkdir(parents=True, exist_ok=True)
    (registry_dir / "registry.toml").write_text(
        '[agent.claude]\nkind = "cli_agent"\ncommand = ["claude"]\ncapabilities = []\n'
        '[agent.codex]\nkind = "cli_agent"\ncommand = ["codex"]\ncapabilities = []\n',
        encoding="utf-8",
    )
    config = MemoryOSConfig(config_path=str(cfg_path))
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "222")
    sent = []
    done_event = _threading.Event()

    call_count = [0]

    def fake_monitor_watch(self):
        call_count[0] += 1
        if call_count[0] == 1:
            # First agent (claude) — rate limit detected via pane monitor
            return ("rate_limited", {"keyword": "quota exceeded", "agent": "claude"})
        # Second agent (codex) — responds cleanly
        return ("done", {"task_id": self.task_id, "sender": "codex", "message": "Привіт! Все добре."})

    monkeypatch.setattr("memory_os.toolkit.agent_state_monitor.AgentStateMonitor.watch", fake_monitor_watch)
    monkeypatch.setattr(
        "memory_os.toolkit.agent_state_monitor.AgentStateMonitor.capture_baseline",
        lambda self: None,
    )
    monkeypatch.setattr(
        "memory_os.toolkit.agent_comm.AgentComm.send",
        lambda self, recipient, message, kind, sender, task_id, **kw: SimpleNamespace(ok=True, error=None),
    )

    def sync_thread(target=None, daemon=None, **kw):
        class _T:
            def start(self):
                target()
                done_event.set()
        return _T()
    monkeypatch.setattr(_threading, "Thread", sync_thread)

    daemon = TelegramPollingDaemon(config, track_tasks=False, swarm_control=True, swarm_watch_timeout=1)
    monkeypatch.setattr(daemon.telegram, "send_message", lambda chat_id, text: sent.append((chat_id, text)) or {"ok": True})

    daemon.process_update({
        "update_id": 500,
        "message": {
            "message_id": 10,
            "from": {"id": 111, "username": "tester"},
            "chat": {"id": 222, "type": "private"},
            "text": "/swarm ну шо там",
        },
    })

    done_event.wait(timeout=5)
    texts = [t for _, t in sent]
    # First dispatch to claude
    # Failover warning (still shown — UX: user needs to know why it's slow)
    assert any("вичерпав ліміт" in t for t in texts), texts
    # Final response from codex
    assert any("Привіт! Все добре." in t for t in texts), texts
    loop_records = [
        json.loads(line)
        for line in (tmp_path / "agent_context" / "loops.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    started = [rec for rec in loop_records if rec.get("event") == "loop.attempt_started"]
    assert [rec["agent_id"] for rec in started] == ["claude", "codex"]
    verdicts = [rec for rec in loop_records if rec.get("event") == "loop.verifier_result"]
    assert [(rec["verdict"], rec["verifier"]) for rec in verdicts] == [
        ("fail", "telegram_polling"),
        ("pass", "telegram_polling"),
    ]


def test_relay_telegram_inbox_first_run_fast_forwards(tmp_path, monkeypatch):
    """First run must not flood the chat with the historical backlog."""
    import json as _json
    from memory_os.toolkit.agent_comm import AgentComm

    monkeypatch.setenv("MEMORY_OS_AGENT_TRANSPORT", "file")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "111")
    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text(_json.dumps({"version": "0.1"}), encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()

    inbox_dir = tmp_path / "agent_context" / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    with (inbox_dir / "telegram.jsonl").open("a", encoding="utf-8") as fh:
        for i in range(5):
            fh.write(_json.dumps({"kind": "STATUS_REPORT", "sender": "codex", "recipient": "telegram", "task_id": f"task_old{i}", "ts": f"2026-07-03T0{i}:00:00+00:00", "message": f"old {i}"}) + "\n")

    config = MemoryOSConfig(config_path=str(cfg_path))
    daemon = TelegramPollingDaemon(config, track_tasks=False, swarm_control=True)
    sent = []
    daemon._send_text = lambda chat_id, text: sent.append((chat_id, text)) or True

    daemon._relay_telegram_inbox()
    assert sent == []  # backlog skipped

    # a NEW untracked message arrives → relayed
    comm = AgentComm(tmp_path)
    with (inbox_dir / "telegram.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(_json.dumps({"kind": "STATUS_REPORT", "sender": "claude", "recipient": "telegram", "task_id": "task_untracked1", "ts": "2026-07-04T10:00:00+00:00", "message": "late reply"}) + "\n")
    daemon._relay_telegram_inbox()
    assert len(sent) == 1
    assert "[claude] late reply" in sent[0][1]

    # idempotent: second call relays nothing
    daemon._relay_telegram_inbox()
    assert len(sent) == 1


def test_watch_core_daemon_restarts_and_notifies_once(tmp_path, monkeypatch):
    """Regression: this watcher used to trust data/daemon_status.json's
    last_activity_time, a field only ever computed in-memory for the IPC
    /status response and never actually persisted to disk by normal daemon
    operation -- so the on-disk copy was permanently stale and every check
    looked "hung" regardless of real daemon health. Liveness must come from
    a live IPC round-trip (DaemonClient), not that file.
    """
    import json as _json
    from memory_os.toolkit.daemon_client import DaemonResponse

    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "111")
    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text(_json.dumps({"version": "0.1"}), encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "data").mkdir()

    config = MemoryOSConfig(config_path=str(cfg_path))
    daemon = TelegramPollingDaemon(config, track_tasks=False, swarm_control=True)
    sent = []
    daemon._send_text = lambda chat_id, text: sent.append((chat_id, text)) or True

    spawned = []
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: spawned.append(a) or None)

    def fake_request(ok):
        def _request(self, path, **kwargs):
            return DaemonResponse(ok=ok, status_code=200 if ok else 0, payload={}, transport="tcp")
        return _request

    # IPC unreachable -- dead branch
    monkeypatch.setattr("memory_os.toolkit.daemon_client.DaemonClient.request", fake_request(False))
    daemon._watch_core_daemon()
    assert len(spawned) == 1
    assert len(sent) == 1
    assert "перезапускаю" in sent[0][1]

    # Second tick inside the same down episode: restart again, but no repeat spam
    daemon._daemon_watch_last = 0
    daemon._watch_core_daemon()
    assert len(spawned) == 2
    assert len(sent) == 1

    # Daemon responds over IPC — episode resets, no messages, even though
    # data/daemon_status.json still doesn't exist on disk at all.
    monkeypatch.setattr("memory_os.toolkit.daemon_client.DaemonClient.request", fake_request(True))
    daemon._daemon_watch_last = 0
    daemon._watch_core_daemon()
    assert len(spawned) == 2
    assert daemon._daemon_down_since == 0.0

    # IPC goes unreachable again -- new down episode, notifies again
    monkeypatch.setattr("memory_os.toolkit.daemon_client.DaemonClient.request", fake_request(False))
    daemon._daemon_watch_last = 0
    daemon._watch_core_daemon()
    assert len(spawned) == 3
    assert len(sent) == 2


def test_run_exits_on_should_stop(tmp_path, monkeypatch):
    """Ctrl+C sets a flag in the CLI handler; run() must honor it and exit."""
    import json as _json

    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "111")
    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text(_json.dumps({"version": "0.1"}), encoding="utf-8")
    (tmp_path / "memory").mkdir()

    config = MemoryOSConfig(config_path=str(cfg_path))
    daemon = TelegramPollingDaemon(config, track_tasks=False, swarm_control=True)

    calls = {"n": 0}

    def fake_get_updates(offset=0, limit=100):
        calls["n"] += 1
        return {"updates": []}

    daemon.telegram.get_updates = fake_get_updates
    daemon._check_and_relay_done_tasks = lambda: None
    daemon._relay_telegram_inbox = lambda: None
    daemon._watch_core_daemon = lambda: None

    stop = {"flag": False}

    def should_stop():
        if calls["n"] >= 3:
            stop["flag"] = True
        return stop["flag"]

    daemon.run(poll_interval=0.01, should_stop=should_stop)
    assert calls["n"] == 3
