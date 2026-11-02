"""Tests for deterministic quota harvesting from codex rollouts and pane mentions."""

import json
import time
import pytest

from memory_os.toolkit.quota_harvester import (
    find_latest_codex_rollout,
    parse_codex_app_server_rate_limits,
    parse_codex_rate_limits,
    read_codex_rate_limits,
    record_limit_mention,
    refresh_quota_state,
)


@pytest.fixture
def root(tmp_path):
    (tmp_path / "agent_context" / "agents").mkdir(parents=True)
    return tmp_path


def _write_rollout(codex_home, day, name, rate_limits=None):
    d = codex_home / "sessions" / "2026" / "07" / day
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    lines = [json.dumps({"timestamp": "t0", "type": "event_msg", "payload": {"type": "user_message"}})]
    if rate_limits:
        lines.append(json.dumps({
            "timestamp": "t1", "type": "event_msg",
            "payload": {"type": "token_count", "info": {}, "rate_limits": rate_limits},
        }))
    f.write_text("\n".join(lines), encoding="utf-8")
    return f


RL = {
    "limit_id": "codex",
    "primary": {"used_percent": 7.5, "window_minutes": 300, "resets_at": 1783134805},
    "secondary": {"used_percent": 61.0, "window_minutes": 10080, "resets_at": 1783524293},
}


def test_parse_codex_rate_limits(tmp_path):
    f = _write_rollout(tmp_path, "03", "rollout-a.jsonl", RL)
    parsed = parse_codex_rate_limits(f)
    assert parsed["usage"]["5h"]["used_percent"] == 7.5
    assert parsed["usage"]["week"]["used_percent"] == 61.0
    assert parsed["usage"]["week"]["resets_at"] == 1783524293
    assert parsed["complete"] is False


def test_parse_codex_app_server_rate_limits_complete_snapshot():
    parsed = parse_codex_app_server_rate_limits({
        "rateLimits": {},
        "rateLimitsByLimitId": {
            "codex": {
                "primary": {
                    "usedPercent": 5,
                    "windowDurationMins": 10080,
                    "resetsAt": 1784557568,
                },
                "secondary": None,
            }
        },
    })

    assert parsed["usage"] == {
        "week": {"used_percent": 5, "resets_at": 1784557568}
    }
    assert parsed["complete"] is True
    assert parsed["source"] == "app_server"


def test_parse_returns_none_without_rate_limits(tmp_path):
    f = _write_rollout(tmp_path, "03", "rollout-b.jsonl", rate_limits=None)
    assert parse_codex_rate_limits(f) is None


def test_find_latest_rollout_by_filename(tmp_path):
    # rollout-new.jsonl sorts after rollout-old.jsonl lexicographically
    old = _write_rollout(tmp_path, "01", "rollout-2026-07-01T10-00-00-old.jsonl", RL)
    new = _write_rollout(tmp_path, "03", "rollout-2026-07-03T10-00-00-new.jsonl", RL)
    import os
    # Make old file newer by mtime to confirm we no longer sort by mtime
    os.utime(old, (1e10, 1e10))
    assert find_latest_codex_rollout(tmp_path) == new



def test_refresh_quota_state_merges_and_persists(root, tmp_path, monkeypatch):
    monkeypatch.setattr("memory_os.toolkit.quota_harvester.read_codex_rate_limits", lambda: None)
    codex_home = tmp_path / "codex_home"
    _write_rollout(codex_home, "03", "rollout-a.jsonl", RL)

    state = refresh_quota_state(root, codex_home=codex_home)
    assert state["codex"]["usage"]["5h"]["used_percent"] == 7.5

    on_disk = json.loads((root / "agent_context" / "agents" / "quota_monitor_state.json").read_text())
    assert on_disk["codex"]["usage"]["week"]["used_percent"] == 61.0
    # exhaustion not implied at 61%
    assert on_disk["codex"].get("has_limit") is not True


def test_refresh_quota_state_ttl_skips_reharvest(root, tmp_path, monkeypatch):
    monkeypatch.setattr("memory_os.toolkit.quota_harvester.read_codex_rate_limits", lambda: None)
    codex_home = tmp_path / "codex_home"
    _write_rollout(codex_home, "03", "rollout-a.jsonl", RL)
    refresh_quota_state(root, codex_home=codex_home)

    # new rollout with different numbers appears, but TTL not expired
    RL2 = {"primary": {"used_percent": 99.0, "window_minutes": 300, "resets_at": 1}, "secondary": {"used_percent": 99.0, "window_minutes": 10080, "resets_at": 2}}
    _write_rollout(codex_home, "03", "rollout-newer.jsonl", RL2)
    state = refresh_quota_state(root, codex_home=codex_home)
    assert state["codex"]["usage"]["5h"]["used_percent"] == 7.5

    state = refresh_quota_state(root, ttl=0.0, codex_home=codex_home)
    assert state["codex"]["usage"]["5h"]["used_percent"] == 99.0


def test_refresh_marks_exhausted_window_as_limit(root, tmp_path, monkeypatch):
    monkeypatch.setattr("memory_os.toolkit.quota_harvester.read_codex_rate_limits", lambda: None)
    codex_home = tmp_path / "codex_home"
    future = time.time() + 3600
    RL_FULL = {"primary": {"used_percent": 100.0, "window_minutes": 300, "resets_at": future}, "secondary": {"used_percent": 40.0, "window_minutes": 10080, "resets_at": future + 100}}
    _write_rollout(codex_home, "03", "rollout-full.jsonl", RL_FULL)
    state = refresh_quota_state(root, codex_home=codex_home)
    assert state["codex"]["has_limit"] is True
    assert state["codex"]["reset_at"] == future


def test_refresh_clears_stale_limit_from_available_partial_snapshot(root, tmp_path, monkeypatch):
    monkeypatch.setattr("memory_os.toolkit.quota_harvester.read_codex_rate_limits", lambda: None)
    codex_home = tmp_path / "codex_home"
    state_path = root / "agent_context" / "agents" / "quota_monitor_state.json"
    state_path.write_text(json.dumps({
        "codex": {
            "has_limit": True,
            "reset_at": time.time() + 3600,
            "attempted_switch": True,
        }
    }), encoding="utf-8")
    weekly_only = {
        "primary": {"used_percent": 2.0, "window_minutes": 10080, "resets_at": time.time() + 7200},
        "secondary": None,
    }
    _write_rollout(codex_home, "03", "rollout-weekly.jsonl", weekly_only)

    state = refresh_quota_state(root, ttl=0.0, codex_home=codex_home)["codex"]

    assert state["usage"] == {
        "week": {
            "used_percent": 2.0,
            "resets_at": weekly_only["primary"]["resets_at"],
        }
    }
    assert state["has_limit"] is False
    assert "reset_at" not in state
    assert "attempted_switch" not in state


def test_record_limit_mention_writes_state(root):
    record_limit_mention(root, "claude", "usage limit reached, try again at 11:28 AM")
    state = json.loads((root / "agent_context" / "agents" / "quota_monitor_state.json").read_text())
    assert state["claude"]["has_limit"] is True
    assert state["claude"]["reset_at"] > time.time() - 86400


def test_limit_summary_renders_harvested_usage(root, tmp_path, monkeypatch):
    monkeypatch.setattr("memory_os.toolkit.quota_harvester.read_codex_rate_limits", lambda: None)
    from memory_os.toolkit.agent_limits import format_agent_limit_summary
    codex_home = tmp_path / "codex_home"
    _write_rollout(codex_home, "03", "rollout-a.jsonl", RL)
    state = refresh_quota_state(root, codex_home=codex_home)
    summary = format_agent_limit_summary(
        spec={"kind": "cli_agent"}, health={}, state=state["codex"],
    )
    assert "5h:" in summary and "61" in summary


def test_status_report_from_codex_triggers_harvest(root, tmp_path, monkeypatch):
    """Closed codex task must refresh usage immediately (ttl bypassed)."""
    import json as _json
    from memory_os.toolkit.agent_comm import AgentComm

    # Explicitly disable the app-server probe rather than relying on CODEX_HOME
    # pointing at a fake dir to incidentally break its auth -- that's a real
    # subprocess side effect, not a deliberate mock, and would silently return
    # live data (overriding the RL fixture below) if the app-server probe ever
    # stops depending on CODEX_HOME for auth.
    monkeypatch.setattr("memory_os.toolkit.quota_harvester.read_codex_rate_limits", lambda: None)
    codex_home = tmp_path / "codex_home"
    _write_rollout(codex_home, "03", "rollout-a.jsonl", RL)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("MEMORY_OS_AGENT_TRANSPORT", "file")

    (root / "memory_os.config.json").write_text(_json.dumps({"version": "0.1"}), encoding="utf-8")
    comm = AgentComm(root)
    comm.send("claude", "done: task finished", kind="STATUS_REPORT", sender="codex", task_id="task_q1")

    state = _json.loads((root / "agent_context" / "agents" / "quota_monitor_state.json").read_text())
    assert state["codex"]["usage"]["week"]["used_percent"] == 61.0


class _FakeStdin:
    def __init__(self):
        self.written = []

    def write(self, data):
        self.written.append(data)

    def flush(self):
        pass


class _FakeStdout:
    def __init__(self, lines):
        self._lines = list(lines)

    def readline(self):
        if not self._lines:
            return ""
        return self._lines.pop(0)

    def fileno(self):
        # select.select is monkeypatched in these tests to avoid needing a
        # real selectable fd; this exists only so isinstance/attr checks
        # elsewhere don't blow up if ever exercised.
        return -1


class _FakeProc:
    def __init__(self, response_lines):
        self.stdin = _FakeStdin()
        self.stdout = _FakeStdout(response_lines)
        self.terminated = False
        self._poll_result = None

    def poll(self):
        return self._poll_result

    def terminate(self):
        self.terminated = True
        self._poll_result = 0

    def wait(self, timeout=None):
        return self._poll_result


def _patch_select_always_ready(monkeypatch):
    monkeypatch.setattr(
        "memory_os.toolkit.quota_harvester.select.select",
        lambda rlist, wlist, xlist, timeout: (rlist, [], []),
    )


def test_read_codex_rate_limits_handshake_and_parses_result(monkeypatch):
    """The riskiest new code path (subprocess + hand-rolled JSON-RPC) had zero
    direct coverage -- every other test monkeypatches it away entirely. This
    drives the real handshake: initialize -> (on id=1 reply) initialized +
    account/rateLimits/read -> parse the id=2 result."""
    response_lines = [
        json.dumps({"id": 1, "result": {}}) + "\n",
        json.dumps({
            "id": 2,
            "result": {
                "rateLimitsByLimitId": {
                    "codex": {
                        "primary": {"usedPercent": 12, "windowDurationMins": 300, "resetsAt": 111},
                        "secondary": {"usedPercent": 34, "windowDurationMins": 10080, "resetsAt": 222},
                    }
                }
            },
        }) + "\n",
    ]
    fake_proc = _FakeProc(response_lines)
    monkeypatch.setattr(
        "memory_os.toolkit.quota_harvester.subprocess.Popen",
        lambda *a, **kw: fake_proc,
    )
    _patch_select_always_ready(monkeypatch)

    result = read_codex_rate_limits(timeout=1.0)

    assert result["source"] == "app_server"
    assert result["complete"] is True
    assert result["usage"]["5h"]["used_percent"] == 12
    assert result["usage"]["week"]["used_percent"] == 34

    # Handshake order: initialize, then (after id=1 reply) initialized + read request.
    written = fake_proc.stdin.written
    assert json.loads(written[0])["method"] == "initialize"
    assert json.loads(written[1])["method"] == "initialized"
    assert json.loads(written[2])["method"] == "account/rateLimits/read"
    assert json.loads(written[2])["id"] == 2

    # Process must not be left running.
    assert fake_proc.terminated is True


def test_read_codex_rate_limits_returns_none_on_missing_binary(monkeypatch):
    def _raise(*a, **kw):
        raise OSError("codex: command not found")

    monkeypatch.setattr("memory_os.toolkit.quota_harvester.subprocess.Popen", _raise)

    assert read_codex_rate_limits(timeout=1.0) is None


def test_read_codex_rate_limits_returns_none_and_cleans_up_on_stall(monkeypatch):
    """No response at all before the deadline -- must give up and terminate
    the process rather than hang or leak it."""
    fake_proc = _FakeProc(response_lines=[])
    monkeypatch.setattr(
        "memory_os.toolkit.quota_harvester.subprocess.Popen",
        lambda *a, **kw: fake_proc,
    )
    # select always reports nothing ready -> immediate break on first check.
    monkeypatch.setattr(
        "memory_os.toolkit.quota_harvester.select.select",
        lambda rlist, wlist, xlist, timeout: ([], [], []),
    )

    result = read_codex_rate_limits(timeout=0.2)

    assert result is None
    assert fake_proc.terminated is True
