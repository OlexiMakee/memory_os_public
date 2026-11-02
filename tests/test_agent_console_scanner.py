import json
from types import SimpleNamespace

from memory_os.toolkit.agent_console_scanner import AgentConsoleScanner


class FakeMultiplexer:
    session_name = "memory_os_workspace"

    def __init__(self, content_by_agent):
        self.content_by_agent = content_by_agent

    def resolve_pane_target(self, agent_id):
        return agent_id

    def list_panes(self, session):
        return [
            SimpleNamespace(target=agent_id, current_command=agent_id)
            for agent_id in self.content_by_agent
        ]

    def capture_pane(self, target, lines=300, full_history=True):
        return self.content_by_agent.get(target, "")


def _write_registry(root):
    agents_dir = root / "agent_context" / "agents"
    agents_dir.mkdir(parents=True)
    (root / "memory_os.config.json").write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    (agents_dir / "registry.toml").write_text(
        """
[agent.agy]
kind = "cli_agent"
command = ["agy"]

[agent.codex]
kind = "cli_agent"
command = ["codex"]

[agent.claude]
kind = "cli_agent"
command = ["claude"]
""",
        encoding="utf-8",
    )


def test_console_scanner_records_existing_strict_limit(tmp_path):
    _write_registry(tmp_path)
    mux = FakeMultiplexer({
        "agy": "idle\nYou've hit your usage limit. Try again at 11:28 AM.",
        "codex": "idle",
    })
    scanner = AgentConsoleScanner(tmp_path, multiplexer=mux)

    events = scanner.scan_once()

    assert len(events) == 1
    assert events[0]["agent_id"] == "agy"
    quota_state = json.loads((tmp_path / "agent_context" / "agents" / "quota_monitor_state.json").read_text(encoding="utf-8"))
    assert quota_state["agy"]["has_limit"] is True
    assert quota_state["agy"]["reset_at"] > 0
    health = json.loads((tmp_path / "agent_context" / "agents" / "health_cache.json").read_text(encoding="utf-8"))
    assert health["agy"]["status"] == "quota_exhausted"

    assert scanner.scan_once() == []


def test_console_scanner_records_delta_limit(tmp_path):
    _write_registry(tmp_path)
    mux = FakeMultiplexer({"agy": "idle\nApproaching rate limits as a discussion topic"})
    scanner = AgentConsoleScanner(tmp_path, multiplexer=mux)

    assert scanner.scan_once() == []

    mux.content_by_agent["agy"] = "idle\nApproaching rate limits as a discussion topic\nquota exceeded, again in 45m"
    events = scanner.scan_once(agent_ids=["agy"])

    assert len(events) == 1
    assert events[0]["agent_id"] == "agy"
    quota_state = json.loads((tmp_path / "agent_context" / "agents" / "quota_monitor_state.json").read_text(encoding="utf-8"))
    assert quota_state["agy"]["has_limit"] is True


def test_console_scanner_ignores_codex_limit_words(tmp_path):
    _write_registry(tmp_path)
    mux = FakeMultiplexer({"codex": 'Search "rate_limits" in rollout file'})

    events = AgentConsoleScanner(tmp_path, multiplexer=mux).scan_once()

    assert events == []
    assert not (tmp_path / "agent_context" / "agents" / "quota_monitor_state.json").exists()


def test_console_scanner_ignores_claude_rate_limit_discussion(tmp_path):
    _write_registry(tmp_path)
    mux = FakeMultiplexer({"claude": "idle"})
    scanner = AgentConsoleScanner(tmp_path, multiplexer=mux)
    assert scanner.scan_once(agent_ids=["claude"]) == []

    mux.content_by_agent["claude"] = (
        "idle\nrollout currently emits only weekly rate-limit window\n"
        "the scanner previously reported quota_exhausted"
    )

    assert scanner.scan_once(agent_ids=["claude"]) == []
    assert not (tmp_path / "agent_context" / "agents" / "quota_monitor_state.json").exists()


def test_console_scanner_records_usage_model_groups(tmp_path):
    _write_registry(tmp_path)
    mux = FakeMultiplexer({
        "agy": """
GEMINI MODELS
  Weekly Limit
    [░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░] 0.00%
    Refreshes in 86h 30m
  Five Hour Limit
    Disabled: You have hit your weekly limit, the 5-hour limit is disabled

CLAUDE AND GPT MODELS
  Weekly Limit
    [███████████████████████████████████████] 100.0
    Quota available
  Five Hour Limit
    [███████████████████████████████████████] 100.0
    Quota available
""",
        "codex": "idle",
    })
    scanner = AgentConsoleScanner(tmp_path, multiplexer=mux)

    events = scanner.scan_once(agent_ids=["agy"])

    assert len(events) == 1
    assert events[0]["agent_id"] == "agy"
    assert events[0]["kind"] == "usage_snapshot"
    assert events[0]["keyword"] == "usage"
    assert events[0]["line"] == "usage screen parsed"
    quota_state = json.loads((tmp_path / "agent_context" / "agents" / "quota_monitor_state.json").read_text(encoding="utf-8"))
    # Gemini exhausted, Claude/GPT available → active group switches to claude_gpt
    assert quota_state["agy"]["active_model_group"] == "claude_gpt"
    # active usage = claude_gpt (100% remaining → 0% used)
    assert quota_state["agy"]["usage"]["week"]["used_percent"] == 0
    # gemini group still recorded
    assert quota_state["agy"]["model_groups"]["gemini"]["week"]["used_percent"] == 100
    # no has_limit because active group is available
    assert quota_state["agy"].get("has_limit") is False

    assert scanner.scan_once(agent_ids=["agy"]) == []
