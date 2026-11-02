"""Tests for the idle-gated /usage pane probe."""

import json
import pytest

from memory_os.toolkit.usage_probe import (
    USAGE_COMMANDS,
    pane_is_idle,
    persist_usage_state,
    parse_usage_screen,
    probe_pane_usage,
)


CLAUDE_USAGE_SCREEN = """\
 Usage

 Current session
 ███████░░░░░░░░░░░░░ 37% used
 Resets 11pm (Europe/Kyiv)

 Current week (all models)
 ██████████████░░░░░░ 72% used
 Resets Jul 8, 1am (Europe/Kyiv)

 Current week (Opus)
 ██░░░░░░░░░░░░░░░░░░ 12% used

 Esc to close
"""


def test_parse_usage_screen_maps_session_and_week():
    usage = parse_usage_screen(CLAUDE_USAGE_SCREEN)
    assert usage["5h"]["used_percent"] == 37
    assert usage["week"]["used_percent"] == 72
    assert "Resets Jul 8" in usage["week"]["resets_note"]
    assert set(usage) == {"5h", "week"}


def test_parse_usage_screen_empty_on_garbage():
    assert parse_usage_screen("just some random pane output\nno percents") == {}


def test_parse_usage_screen_wrapped_lines():
    screen = """
  Current week (all models)
  ██████████████░░░░░░ 72% used
  Resets Jul 10,
  1am (Europe/Kyiv)
    """
    usage = parse_usage_screen(screen)
    assert usage["week"]["used_percent"] == 72
    assert usage["week"]["resets_note"] == "Resets Jul 10, 1am (Europe/Kyiv)"


def test_pane_is_idle():
    assert pane_is_idle("some output\n> \n? for shortcuts") is True
    assert pane_is_idle("stuff\n* Working (13s • esc to interrupt)") is False
    assert pane_is_idle(None) is False
    assert pane_is_idle("press ctrl+c again to exit") is False


def test_agy_has_usage_command():
    assert "agy" in USAGE_COMMANDS


@pytest.fixture
def root(tmp_path):
    (tmp_path / "agent_context" / "agents").mkdir(parents=True)
    (tmp_path / "memory_os.config.json").write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    return tmp_path


def _fake_mgr_factory(screens, sent):
    class FakeMgr:
        def __init__(self, *a, **kw):
            pass

        def resolve_pane_target(self, target):
            return "0"

        def capture_pane(self, target, lines=50):
            return screens.pop(0) if screens else ""

        def send_keys(self, target, message, **kw):
            sent.append(("keys", message))

        def send_shortcut(self, target, name):
            sent.append(("shortcut", name))
            return True

    return FakeMgr


def test_probe_skips_busy_pane(root, monkeypatch):
    sent = []
    screens = ["● Working (5s • esc to interrupt)"]
    monkeypatch.setattr(
        "memory_os.toolkit.multiplexer_manager.MultiplexerManager",
        _fake_mgr_factory(screens, sent),
    )
    assert probe_pane_usage(root, "claude") is None
    assert sent == []  # nothing injected


def test_probe_harvests_and_persists(root, monkeypatch):
    sent = []
    screens = [">", CLAUDE_USAGE_SCREEN]
    monkeypatch.setattr(
        "memory_os.toolkit.multiplexer_manager.MultiplexerManager",
        _fake_mgr_factory(screens, sent),
    )
    usage = probe_pane_usage(root, "claude", timeout=1.0, poll_interval=0.01)
    assert usage["5h"]["used_percent"] == 37
    assert ("keys", "/usage") in sent
    assert ("shortcut", "escape") in sent

    state = json.loads((root / "agent_context" / "agents" / "quota_monitor_state.json").read_text())
    assert state["claude"]["usage"]["week"]["used_percent"] == 72
    assert state["claude"]["has_limit"] is False


def test_probe_unknown_agent_skipped(root):
    assert probe_pane_usage(root, "unknown_agent") is None


def test_parse_usage_screen_new_style():
    screen = """
GEMINI MODELS
  Models within this group: Gemini Flash, Gemini Pro

  Weekly Limit
    [██████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░] 51.63
    52% remaining · Refreshes in 132h 2m

  Five Hour Limit
    [█████████████████████████████████████░░░░░░░░░░░░░] 73.71
    74% remaining · Refreshes in 4h 18m
"""
    parsed = parse_usage_screen(screen)
    assert parsed["gemini"]["week"]["used_percent"] == 48
    assert parsed["gemini"]["5h"]["used_percent"] == 26
    assert "Refreshes in 132h" in parsed["gemini"]["week"]["resets_note"]
    assert "Refreshes in 4h" in parsed["gemini"]["5h"]["resets_note"]


def test_parse_usage_screen_new_style_model_groups():
    screen = """
GEMINI MODELS
  Models within this group: Gemini Flash, Gemini Pro

  Weekly Limit
    [░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░] 0.00%
    Refreshes in 86h 30m

  Five Hour Limit
    Disabled: You have hit your weekly limit, the 5-hour limit is disabled

CLAUDE AND GPT MODELS
  Models within this group: Claude Opus, Claude Sonnet, GPT

  Weekly Limit
    [███████████████████████████████████████] 100.0
    Quota available

  Five Hour Limit
    [███████████████████████████████████████] 100.0
    Quota available
"""
    parsed = parse_usage_screen(screen)

    assert parsed["gemini"]["week"]["used_percent"] == 100
    assert parsed["gemini"]["5h"]["used_percent"] == 100
    assert parsed["gemini"]["5h"]["status"] == "disabled"
    assert parsed["claude_gpt"]["week"]["used_percent"] == 0
    assert parsed["claude_gpt"]["5h"]["used_percent"] == 0
    assert parsed["claude_gpt"]["week"]["available"] is True


def test_persist_usage_state_keeps_model_groups(root):
    parsed = {
        "gemini": {
            "week": {"used_percent": 100, "resets_note": "Refreshes in 86h 30m"},
            "5h": {"used_percent": 100, "status": "disabled", "available": False},
        },
        "claude_gpt": {
            "week": {"used_percent": 0, "available": True},
            "5h": {"used_percent": 0, "available": True},
        },
    }

    usage = persist_usage_state(root, "agy", parsed)

    # Gemini exhausted but Claude/GPT available → active group is claude_gpt
    assert usage["week"]["used_percent"] == 0
    state = json.loads((root / "agent_context" / "agents" / "quota_monitor_state.json").read_text())
    assert state["agy"]["has_limit"] is False
    assert state["agy"]["active_model_group"] == "claude_gpt"
    assert state["agy"]["model_groups"]["gemini"]["week"]["used_percent"] == 100
    assert state["agy"]["model_groups"]["claude_gpt"]["week"]["used_percent"] == 0
