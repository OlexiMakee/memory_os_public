import sys

from memory_os.toolkit.startup_profile import (
    DEFAULT_PROFILE,
    STARTUP_PROFILES,
    apply_profile_to_flags,
    read_startup_profile,
    record_startup_profile,
    select_startup_profile,
)


def test_full_autonomy_is_first_and_default():
    assert STARTUP_PROFILES[0][1] == "full_autonomy"
    assert DEFAULT_PROFILE == "full_autonomy"


def test_apply_profile_full_autonomy_keeps_flags():
    flags = ["--dangerously-skip-permissions"]
    assert apply_profile_to_flags(flags, "full_autonomy") == flags


def test_apply_profile_supervised_strips_unattended_flags():
    assert apply_profile_to_flags(["--dangerously-skip-permissions"], "supervised") == []
    assert apply_profile_to_flags(
        ["--sandbox", "danger-full-access", "--ask-for-approval", "never"], "supervised"
    ) == []


def test_apply_profile_supervised_keeps_unrelated_flags():
    flags = ["-c", "model_reasoning_effort=medium"]
    assert apply_profile_to_flags(flags, "supervised") == flags


def test_select_startup_profile_non_interactive_returns_default(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert select_startup_profile() == DEFAULT_PROFILE


def test_record_and_read_startup_profile_roundtrip(tmp_path):
    record_startup_profile(tmp_path, "supervised")
    assert read_startup_profile(tmp_path) == "supervised"


def test_read_startup_profile_defaults_when_absent(tmp_path):
    assert read_startup_profile(tmp_path) == DEFAULT_PROFILE


def test_read_startup_profile_rejects_unknown_value(tmp_path):
    runtime_dir = tmp_path / "agent_context" / "runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "startup_profile.json").write_text('{"profile": "godmode"}', encoding="utf-8")
    assert read_startup_profile(tmp_path) == DEFAULT_PROFILE
