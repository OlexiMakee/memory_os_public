import json
import subprocess
from pathlib import Path
from io import BytesIO
from urllib.error import HTTPError
import urllib.request
import pytest

from memory_os.core.config import MemoryOSConfig
from memory_os.core.daemon import MemoryDaemon
from memory_os.toolkit.daemon_hygiene import DaemonHygiene
from memory_os.toolkit.task_kernel import TaskKernel


def make_daemon_root(tmp_path: Path) -> MemoryOSConfig:
    (tmp_path / "agent_context").mkdir()
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "nodes.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "edges.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "events.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "agent_context" / "task_capsules.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory_os.config.json").write_text(
        json.dumps({
            "memory_dir": "memory",
            "db_path": "memory/memory_os.db",
            "daemon_port": 0
        }),
        encoding="utf-8",
    )
    return MemoryOSConfig(str(tmp_path / "memory_os.config.json"))


def test_daemon_auto_dispatches_pending_task(tmp_path, monkeypatch):
    config = make_daemon_root(tmp_path)
    kernel = TaskKernel(tmp_path)
    task = kernel.create("daemon task", risk="low", capabilities=["run_tests"])
    from memory_os.toolkit.dispatcher import DispatcherEngine as RealDispatcherEngine

    class FakePlan:
        task_id = task["id"]
        agent = "shell"
        agent_kind = "shell"
        text = "daemon task"
        requires_review = False

    class FakeRouter:
        def __init__(self, root):
            self.root = root

        def route(self, task_id=None):
            assert task_id == task["id"]
            return FakePlan()

    class FakeDispatcher:
        def __init__(self, root):
            self.root = root

        def dispatch_plan(self, plan):
            return self.shell(plan.task_id, ["echo", "ok"], dry_run=False)

        def shell(self, task_id, cmd, dry_run=False):
            return RealDispatcherEngine(self.root).shell(task_id, cmd, dry_run=dry_run)

    monkeypatch.setattr("memory_os.toolkit.router_plan.RouterPlan", FakeRouter)
    monkeypatch.setattr("memory_os.toolkit.dispatcher.DispatcherEngine", FakeDispatcher)

    daemon = MemoryDaemon(config, tmp_path / "transcript.jsonl")
    result = daemon.auto_dispatch_tasks()

    updated = kernel.get(task["id"])
    assert result["dispatched"] == 1
    assert updated["status"] == "done"
    ev_dir = tmp_path / "agent_context" / "evidence" / task["id"]
    assert ev_dir.exists()
    assert list(ev_dir.glob("*_shell_dispatch.json"))


def test_daemon_skips_high_risk_pending_task(tmp_path, monkeypatch):
    config = make_daemon_root(tmp_path)
    kernel = TaskKernel(tmp_path)
    task = kernel.create("high risk task", risk="high", capabilities=["code_edit"])

    class FakePlan:
        task_id = task["id"]
        agent = "claude"
        agent_kind = "cli_agent"
        text = "high risk task"
        requires_review = True

    class FakeRouter:
        def __init__(self, root):
            self.root = root

        def route(self, task_id=None):
            return FakePlan()

    monkeypatch.setattr("memory_os.toolkit.router_plan.RouterPlan", FakeRouter)

    daemon = MemoryDaemon(config, tmp_path / "transcript.jsonl")
    result = daemon.auto_dispatch_tasks()

    assert result["skipped"] == 1
    assert kernel.get(task["id"])["status"] == "pending"


def test_daemon_blocks_task_on_dispatch_exception(tmp_path, monkeypatch):
    config = make_daemon_root(tmp_path)
    kernel = TaskKernel(tmp_path)
    task = kernel.create("failing dispatch task", risk="low", capabilities=["run_tests"])

    class FakePlan:
        task_id = task["id"]
        agent = "shell"
        agent_kind = "shell"
        text = "failing dispatch task"
        requires_review = False

    class FakeRouter:
        def __init__(self, root):
            self.root = root

        def route(self, task_id=None):
            return FakePlan()

    class FailingDispatcher:
        def __init__(self, root):
            self.root = root

        def dispatch_plan(self, plan):
            raise RuntimeError("boom")

    monkeypatch.setattr("memory_os.toolkit.router_plan.RouterPlan", FakeRouter)
    monkeypatch.setattr("memory_os.toolkit.dispatcher.DispatcherEngine", FailingDispatcher)

    daemon = MemoryDaemon(config, tmp_path / "transcript.jsonl")
    result = daemon.auto_dispatch_tasks()

    updated = kernel.get(task["id"])
    assert result["errors"] == 1
    assert updated["status"] == "blocked"
    assert "auto-dispatch error" in updated["blocked_reason"]


def test_daemon_blocks_unroutable_capability_task_without_dispatch(tmp_path, monkeypatch):
    config = make_daemon_root(tmp_path)
    kernel = TaskKernel(tmp_path)
    task = kernel.create("code edit", risk="medium", capabilities=["code_edit"])

    class FakePlan:
        task_id = task["id"]
        agent = "unavailable"
        agent_kind = "unavailable"
        text = "code edit"
        requires_review = False
        blocked_reason = "No available cli_agent for required capabilities: code_edit"

    class FakeRouter:
        def __init__(self, root):
            self.root = root

        def route(self, task_id=None):
            return FakePlan()

    class RejectDispatch:
        def __init__(self, root):
            raise AssertionError("dispatcher must not be constructed for a blocked plan")

    monkeypatch.setattr("memory_os.toolkit.router_plan.RouterPlan", FakeRouter)
    monkeypatch.setattr("memory_os.toolkit.dispatcher.DispatcherEngine", RejectDispatch)

    daemon = MemoryDaemon(config, tmp_path / "transcript.jsonl")
    result = daemon.auto_dispatch_tasks()

    updated = kernel.get(task["id"])
    assert result["blocked"] == 1
    assert updated["status"] == "blocked"
    assert updated["blocked_reason"] == FakePlan.blocked_reason


def test_unix_domain_socket_ipc_and_fallback(tmp_path):
    import os
    import socket
    import tempfile
    if not hasattr(socket, "AF_UNIX"):
        return

    config = make_daemon_root(tmp_path)
    daemon = MemoryDaemon(config, tmp_path / "transcript.jsonl")

    # On macOS, tmp_path paths under /private/var/folders can exceed the 104-byte AF_UNIX sockaddr limit.
    # Use a short /tmp directory for the unix domain socket test.
    short_sock_dir = tempfile.TemporaryDirectory(dir="/tmp")
    daemon.socket_path = os.path.join(short_sock_dir.name, "m.sock")

    # Start IPC server
    daemon.ipc_server.start()
    if daemon.http_server is None:
        short_sock_dir.cleanup()
        return
    try:
        # Test direct unix socket query
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(2.0)
        client.connect(daemon.socket_path)
        client.sendall(b"GET /status HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
        resp = b""
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            resp += chunk
        client.close()

        assert b"200 OK" in resp or b"200" in resp
        assert b"running" in resp or b"config" in resp
    finally:
        if daemon.http_server:
            daemon.http_server.shutdown()
        if getattr(daemon, "unix_server", None):
            daemon.unix_server.shutdown()
        if os.path.exists(daemon.socket_path):
            try:
                os.unlink(daemon.socket_path)
            except OSError:
                pass
        short_sock_dir.cleanup()


def test_daemon_rejects_unsafe_space_switch(tmp_path):
    config = make_daemon_root(tmp_path)
    daemon = MemoryDaemon(config, tmp_path / "transcript.jsonl")

    assert daemon.switch_space("../../tmp") is False
    assert daemon.config.space == "default"


def test_space_endpoint_returns_400_for_unsafe_space(tmp_path):
    config = make_daemon_root(tmp_path)
    daemon = MemoryDaemon(config, tmp_path / "transcript.jsonl")
    daemon.start_ipc_server()
    if daemon.http_server is None:
        return

    port = daemon.http_server.server_address[1]
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/space",
        data=json.dumps({"space": "../../tmp"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        try:
            urllib.request.urlopen(req, timeout=3)
            raise AssertionError("expected HTTPError")
        except HTTPError as exc:
            assert exc.code == 400
            body = exc.read().decode("utf-8")
            assert "invalid space" in body
    finally:
        if daemon.http_server:
            daemon.http_server.shutdown()
        if getattr(daemon, "unix_server", None):
            daemon.unix_server.shutdown()
        if daemon.socket_path and Path(daemon.socket_path).exists():
            try:
                Path(daemon.socket_path).unlink()
            except OSError:
                pass


def test_cmd_switch_space_reports_invalid_space(tmp_path, monkeypatch, capsys):
    config = make_daemon_root(tmp_path)

    def fake_urlopen(req, timeout=5):
        raise HTTPError(
            req.full_url,
            400,
            "Bad Request",
            hdrs=None,
            fp=BytesIO(b'{"error":"invalid space"}'),
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    from memory_os.cli import cmd_switch_space

    args = type("Args", (), {"target_space": "../../tmp"})()
    code = cmd_switch_space(args, config)
    out = capsys.readouterr().out

    assert code == 1
    assert "Failed to switch daemon space: invalid space" in out


def test_daemon_hygiene_writes_runtime_and_relay_snapshots(tmp_path, monkeypatch):
    config = make_daemon_root(tmp_path)
    (tmp_path / "agent_context" / "agents").mkdir(parents=True, exist_ok=True)
    (tmp_path / "agent_context" / "agents" / "registry.toml").write_text(
        """
[agent.codex]
kind = "cli_agent"
command = ["codex"]
tmux_target = "test:0.1"
""",
        encoding="utf-8",
    )
    done_dir = tmp_path / "agent_context" / "done"
    done_dir.mkdir(parents=True, exist_ok=True)
    (done_dir / "task_demo.json").write_text(json.dumps({"task_id": "task_demo"}), encoding="utf-8")

    class FakePane:
        def __init__(self, target, command):
            self.target = target
            self.current_command = command

    panes = [FakePane("1", "codex"), FakePane("4", "python3 -m memory_os telegram-daemon --swarm-control")]
    targets = {"codex": "1", "telegram-chat": "4"}

    monkeypatch.setattr("memory_os.toolkit.multiplexer_manager.MultiplexerManager.resolve_pane_target", lambda self, agent_id: targets[agent_id])
    monkeypatch.setattr("memory_os.toolkit.multiplexer_manager.MultiplexerManager.list_panes", lambda self, session: panes)
    monkeypatch.setattr("memory_os.toolkit.multiplexer_manager.MultiplexerManager.capture_pane", lambda self, target, lines=40: "> typing something...")

    report = DaemonHygiene(config.root_dir).run_once()

    assert report["runtime_health"]["agents"]["codex"]["is_active"] is True
    assert report["runtime_health"]["agents"]["codex"]["is_working"] is True
    assert report["relay_watch"]["pending_done_count"] == 1
    assert report["telegram_daemon"] == {"checked": True, "alive": True}
    assert (tmp_path / "agent_context" / "agents" / "runtime_health.json").exists()
    assert (tmp_path / "agent_context" / "agents" / "relay_watch.json").exists()


def test_check_telegram_daemon_no_session_skips(tmp_path, monkeypatch):
    config = make_daemon_root(tmp_path)
    monkeypatch.setattr("memory_os.toolkit.multiplexer_manager.MultiplexerManager.list_panes", lambda self, session: [])
    result = DaemonHygiene(config.root_dir).check_telegram_daemon()
    assert result == {"checked": False, "reason": "no workspace session"}


def test_check_telegram_daemon_dead_pane_restarts(tmp_path, monkeypatch):
    config = make_daemon_root(tmp_path)

    class FakePane:
        target = "4"
        current_command = ""  # pane exited — no command running

    monkeypatch.setattr("memory_os.toolkit.multiplexer_manager.MultiplexerManager.resolve_pane_target", lambda self, agent_id: "4")
    monkeypatch.setattr("memory_os.toolkit.multiplexer_manager.MultiplexerManager.list_panes", lambda self, session: [FakePane()])

    calls = []

    class FakeRuntimeControl:
        def restart_pane(self, pane_name):
            calls.append(pane_name)
            return type("Step", (), {"ok": True, "detail": "restarted"})()

    result = DaemonHygiene(config.root_dir, runtime_control=FakeRuntimeControl()).check_telegram_daemon()
    assert result == {"checked": True, "alive": False, "restarted": True}
    assert calls == ["telegram-chat"]


# ---------------------------------------------------------------------------
# Ghost pane reconciliation tests
# ---------------------------------------------------------------------------

def _write_registry(tmp_path: Path, agents: dict) -> None:
    reg_dir = tmp_path / "agent_context" / "agents"
    reg_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for agent_id, extra in agents.items():
        lines.append(f'[agent.{agent_id}]')
        lines.append('kind = "cli_agent"')
        for k, v in extra.items():
            lines.append(f'{k} = "{v}"')
    (reg_dir / "registry.toml").write_text("\n".join(lines), encoding="utf-8")


class _FakePane:
    def __init__(self, target: str, command: str):
        self.target = target
        self.current_command = command
        self.active = True
        self.width = 80
        self.height = 24


def test_snapshot_marks_bash_pane_as_ghost(tmp_path, monkeypatch):
    """Pane slot exists but runs bash (agent crashed) → is_ghost=True, is_active=False."""
    config = make_daemon_root(tmp_path)
    _write_registry(tmp_path, {"codex": {"tmux_target": "test:0.1"}})

    panes = [_FakePane("test:0.1", "bash")]  # codex slot occupied by bash
    monkeypatch.setattr(
        "memory_os.toolkit.multiplexer_manager.MultiplexerManager.list_panes",
        lambda self, session: panes,
    )
    monkeypatch.setattr(
        "memory_os.toolkit.multiplexer_manager.MultiplexerManager.resolve_pane_target",
        lambda self, agent_id: "test:0.1",
    )

    report = DaemonHygiene(config.root_dir).snapshot_runtime_health()
    codex = report["agents"]["codex"]
    assert codex["is_ghost"] is True
    assert codex["is_active"] is False
    assert codex["target_pane"] == "offline"


def test_snapshot_session_crash_writes_all_offline(tmp_path, monkeypatch):
    """If list_panes raises, snapshot writes explicit offline for every agent."""
    config = make_daemon_root(tmp_path)
    _write_registry(tmp_path, {"claude": {}, "codex": {}})

    monkeypatch.setattr(
        "memory_os.toolkit.multiplexer_manager.MultiplexerManager.list_panes",
        lambda self, session: (_ for _ in ()).throw(RuntimeError("tmux not running")),
    )

    report = DaemonHygiene(config.root_dir).snapshot_runtime_health()

    assert report["session_alive"] is False
    assert "session_error" in report
    for agent_id in ("claude", "codex"):
        a = report["agents"][agent_id]
        assert a["is_active"] is False
        assert a["target_pane"] == "offline"
    # Snapshot must be written even on crash
    assert (tmp_path / "agent_context" / "agents" / "runtime_health.json").exists()
    saved = json.loads((tmp_path / "agent_context" / "agents" / "runtime_health.json").read_text())
    assert saved["session_alive"] is False


def test_snapshot_live_agent_pane_not_ghost(tmp_path, monkeypatch):
    """Pane running the correct binary → is_ghost=False, is_active=True."""
    config = make_daemon_root(tmp_path)
    _write_registry(tmp_path, {"claude": {"tmux_target": "mem:0.0"}})

    panes = [_FakePane("mem:0.0", "claude")]
    monkeypatch.setattr(
        "memory_os.toolkit.multiplexer_manager.MultiplexerManager.list_panes",
        lambda self, session: panes,
    )
    monkeypatch.setattr(
        "memory_os.toolkit.multiplexer_manager.MultiplexerManager.resolve_pane_target",
        lambda self, agent_id: "mem:0.0",
    )
    monkeypatch.setattr(
        "memory_os.toolkit.multiplexer_manager.MultiplexerManager.capture_pane",
        lambda self, target, lines=40: "claude> idle",
    )

    report = DaemonHygiene(config.root_dir).snapshot_runtime_health()
    agent = report["agents"]["claude"]
    assert agent["is_ghost"] is False
    assert agent["is_active"] is True
    assert agent["target_pane"] == "mem:0.0"


@pytest.mark.parametrize(
    ("agent_id", "command"),
    [
        ("claude", "claude --continue --dangerously-skip-permissions"),
        ("agy", "agy --continue --dangerously-skip-permissions"),
        ("codex", "/opt/codex/bin/codex-code-mode-host"),
    ],
)
def test_agent_pane_alive_accepts_runtime_command_lines(tmp_path, agent_id, command):
    hygiene = DaemonHygiene(tmp_path)

    assert hygiene._agent_pane_alive(agent_id, command) is True
    assert hygiene._agent_pane_alive(agent_id, "bash") is False


def test_reconcile_agent_panes_restarts_workers_and_protects_claude(tmp_path):
    calls = []

    class FakeRuntimeControl:
        def restart_pane(self, agent_id):
            calls.append(agent_id)
            return type("Step", (), {"ok": True, "detail": "restarted"})()

    runtime_health = {
        "session_alive": True,
        "agents": {
            "claude": {"is_ghost": True},
            "codex": {"is_ghost": True},
            "agy": {"is_ghost": True},
            "hermes": {"is_ghost": True},
        },
    }

    result = DaemonHygiene(tmp_path, runtime_control=FakeRuntimeControl()).reconcile_agent_panes(
        runtime_health
    )

    assert calls == ["codex", "agy", "hermes"]
    assert result["restarted"] == ["codex", "agy", "hermes"]
    assert result["protected"] == ["claude"]
    assert result["failed"] == []


def test_reconcile_agent_panes_applies_restart_cooldown(tmp_path, monkeypatch):
    calls = []

    class FakeRuntimeControl:
        def restart_pane(self, agent_id):
            calls.append(agent_id)
            return type("Step", (), {"ok": False, "detail": "still dead"})()

    runtime_health = {
        "session_alive": True,
        "agents": {"codex": {"is_ghost": True}},
    }
    monkeypatch.setattr("memory_os.toolkit.daemon_hygiene.time.time", lambda: 1000.0)
    hygiene = DaemonHygiene(tmp_path, runtime_control=FakeRuntimeControl())

    first = hygiene.reconcile_agent_panes(runtime_health, cooldown_seconds=300.0)
    second = hygiene.reconcile_agent_panes(runtime_health, cooldown_seconds=300.0)

    assert calls == ["codex"]
    assert first["failed"] == [{"agent_id": "codex", "detail": "still dead"}]
    assert second["cooldown"] == ["codex"]


def test_snapshot_missing_pane_not_ghost(tmp_path, monkeypatch):
    """Pane slot absent (agent never started) → is_ghost=False, is_active=False."""
    config = make_daemon_root(tmp_path)
    _write_registry(tmp_path, {"agy": {"tmux_target": "mem:0.2"}})

    monkeypatch.setattr(
        "memory_os.toolkit.multiplexer_manager.MultiplexerManager.list_panes",
        lambda self, session: [],  # no panes at all
    )
    monkeypatch.setattr(
        "memory_os.toolkit.multiplexer_manager.MultiplexerManager.resolve_pane_target",
        lambda self, agent_id: "mem:0.2",
    )

    report = DaemonHygiene(config.root_dir).snapshot_runtime_health()
    agent = report["agents"]["agy"]
    assert agent["is_ghost"] is False   # not a ghost — just absent
    assert agent["is_active"] is False
    assert agent["target_pane"] == "offline"


def test_daemon_housekeeping_runs_hygiene(tmp_path, monkeypatch):
    config = make_daemon_root(tmp_path)
    daemon = MemoryDaemon(config, tmp_path / "transcript.jsonl")
    calls = []

    class FakeHygiene:
        def __init__(self, root):
            self.root = root

        def run_once(self):
            calls.append(str(self.root))
            return {"relay_watch": {"lagging_done_count": 0, "stale_lease_count": 0}}

    monkeypatch.setattr("memory_os.toolkit.daemon_hygiene.DaemonHygiene", FakeHygiene)
    daemon.housekeeping()
    assert calls == [str(tmp_path)]


def test_daemon_housekeeping_retries_done_relay_and_heals_stale_leases(tmp_path, monkeypatch):
    config = make_daemon_root(tmp_path)
    daemon = MemoryDaemon(config, tmp_path / "transcript.jsonl")
    kernel = TaskKernel(tmp_path)
    task = kernel.create("Lease stale")
    kernel.claim(task["id"], "agent-old", lease_minutes=-1)
    calls = {"watch_done_files": 0}

    class FakeHygiene:
        def __init__(self, root):
            self.root = root

        def run_once(self):
            return {"relay_watch": {"lagging_done_count": 1, "stale_lease_count": 1}}

    monkeypatch.setattr("memory_os.toolkit.daemon_hygiene.DaemonHygiene", FakeHygiene)
    monkeypatch.setattr(daemon.housekeeper, "watch_done_files", lambda: calls.__setitem__("watch_done_files", calls["watch_done_files"] + 1))

    daemon.housekeeping()

    assert calls["watch_done_files"] == 1
    assert kernel.get(task["id"])["status"] == "pending"


def test_daemon_jobs_skip_under_load(tmp_path, monkeypatch):
    from memory_os.core.resource_guard import ResourceGuard, LoadSnapshot
    
    config = make_daemon_root(tmp_path)
    daemon = MemoryDaemon(config, tmp_path / "transcript.jsonl")

    # Mock ResourceGuard to return unsafe
    monkeypatch.setattr(ResourceGuard, "is_safe", lambda self: False)
    monkeypatch.setattr(ResourceGuard, "snapshot", lambda self: LoadSnapshot(cpu=95.0, ram=90.0, temp=85.0))

    # Track logging calls
    warnings = []
    monkeypatch.setattr(daemon.logger, "warning", lambda msg: warnings.append(msg))

    # Run the heavy jobs
    daemon.run_link_infer()
    daemon.run_decay_nodes()
    daemon.auto_compact()

    # Verify that all 3 jobs were skipped and logged warnings containing "skipped"
    assert len(warnings) == 3
    assert any("Link inference skipped" in w for w in warnings)
    assert any("Decay nodes skipped" in w for w in warnings)
    assert any("Auto-compaction skipped: machine is under load" in w for w in warnings)


def test_watch_done_files_does_not_replay_backlog_after_restart(tmp_path, monkeypatch):
    """Regression: without pre-population, every daemon restart re-relayed
    the entire historical done/ backlog into claude's pane in one burst
    (confirmed live: 2267 stale events fired in ~1s). Files already on disk
    when the daemon starts must be treated as already-processed."""
    config = make_daemon_root(tmp_path)
    done_dir = tmp_path / "agent_context" / "done"
    done_dir.mkdir(parents=True, exist_ok=True)
    for i in range(5):
        (done_dir / f"task_old_{i}.json").write_text(
            json.dumps({"task_id": f"task_old_{i}", "sender": "codex", "message": "done"}),
            encoding="utf-8",
        )

    # Simulate a fresh process (new daemon instance, same pre-existing files)
    daemon = MemoryDaemon(config, tmp_path / "transcript.jsonl")
    assert daemon._processed_done == {f"task_old_{i}.json" for i in range(5)}

    events_path = tmp_path / "agent_context" / "task_events.jsonl"
    before = events_path.read_text(encoding="utf-8") if events_path.exists() else ""

    daemon.watch_done_files()

    after = events_path.read_text(encoding="utf-8") if events_path.exists() else ""
    assert after == before, "pre-existing done files must not be re-relayed on restart"

    # A genuinely new done file (created after startup) must still relay normally
    (done_dir / "task_new.json").write_text(
        json.dumps({"task_id": "task_new", "sender": "agy", "message": "fresh"}),
        encoding="utf-8",
    )
    daemon.watch_done_files()
    new_content = events_path.read_text(encoding="utf-8")
    assert "task_new" in new_content
    assert "task_old_0" not in new_content


def test_daemon_scheduler_intervals_are_config_overridable(tmp_path):
    """Regression: the 9 scheduler.add_task intervals + auto-compact trigger
    thresholds were hardcoded literals with no config override, unlike
    DiskGuard/ResourceGuard's config.data pattern.
    """
    (tmp_path / "agent_context").mkdir()
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "nodes.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "edges.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "events.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "agent_context" / "task_capsules.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory_os.config.json").write_text(
        json.dumps({
            "memory_dir": "memory",
            "db_path": "memory/memory_os.db",
            "daemon_port": 0,
            "daemon": {
                "watch_transcript_sec": 1.0,
                "auto_compact_min_uncompacted": 7,
            },
        }),
        encoding="utf-8",
    )
    config = MemoryOSConfig(str(tmp_path / "memory_os.config.json"))

    daemon = MemoryDaemon(config, tmp_path / "transcript.jsonl")

    assert daemon.schedule_settings["watch_transcript_sec"] == 1.0
    assert daemon.schedule_settings["auto_compact_min_uncompacted"] == 7
    # Unconfigured keys keep their documented defaults.
    assert daemon.schedule_settings["housekeeping_sec"] == 60.0

    watch_transcript_task = next(t for t in daemon.scheduler.tasks if t["name"] == "watch_transcript")
    assert watch_transcript_task["interval"] == 1.0


def test_daemon_ingest_and_compact_provider_are_config_overridable(tmp_path):
    """Item 34: _do_ingest/auto_compact hardcoded provider="gemini" with no
    override. Made config-driven with "gemini" as the explicit, behavior-
    preserving default -- NOT rewired through RoutingPolicy, since that
    routes these task types to a local ollama model, a real quality
    change, not just a hardcoding fix.
    """
    (tmp_path / "agent_context").mkdir()
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "nodes.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "edges.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "events.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "agent_context" / "task_capsules.jsonl").write_text("", encoding="utf-8")

    (tmp_path / "memory_os.config.json").write_text(
        json.dumps({
            "memory_dir": "memory",
            "db_path": "memory/memory_os.db",
            "daemon_port": 0,
        }),
        encoding="utf-8",
    )
    default_daemon = MemoryDaemon(MemoryOSConfig(str(tmp_path / "memory_os.config.json")), tmp_path / "transcript.jsonl")
    assert default_daemon.schedule_settings["ingest_provider"] == "gemini"
    assert default_daemon.schedule_settings["compact_provider"] == "gemini"

    (tmp_path / "memory_os.config.json").write_text(
        json.dumps({
            "memory_dir": "memory",
            "db_path": "memory/memory_os.db",
            "daemon_port": 0,
            "daemon": {"ingest_provider": "ollama", "compact_provider": "ollama"},
        }),
        encoding="utf-8",
    )
    overridden_daemon = MemoryDaemon(MemoryOSConfig(str(tmp_path / "memory_os.config.json")), tmp_path / "transcript.jsonl")
    assert overridden_daemon.schedule_settings["ingest_provider"] == "ollama"
    assert overridden_daemon.schedule_settings["compact_provider"] == "ollama"
