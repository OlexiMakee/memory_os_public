from unittest.mock import MagicMock

import argparse

import pytest

from memory_os.cli import cmd_xfce
from memory_os.core.config import MemoryOSConfig
from memory_os.toolkit.xfce_manager import (
    XFCEManager,
    diff_xfce_summaries,
    read_xfce_cache,
    render_snapshot_text,
    render_summary_diff_text,
    sync_xfce_cache,
    write_xfce_cache,
)


def test_channels_parses_xfconf_output():
    def runner(cmd, **kwargs):
        assert cmd == ["xfconf-query", "-l"]
        return MagicMock(returncode=0, stdout="Channels:\n  xfwm4\n  xsettings\n", stderr="")

    manager = XFCEManager(runner=runner)
    assert manager.channels() == ["xfwm4", "xsettings"]


def test_set_uses_explicit_type_and_create_flag():
    calls = []

    def runner(cmd, **kwargs):
        calls.append(cmd)
        return MagicMock(returncode=0, stdout="", stderr="")

    manager = XFCEManager(runner=runner)
    manager.set("xfwm4", "/general/use_compositing", "false", "bool", create=True)

    assert calls == [
        [
            "xfconf-query",
            "-c",
            "xfwm4",
            "-p",
            "/general/use_compositing",
            "-s",
            "false",
            "-t",
            "bool",
            "-n",
        ]
    ]


def test_set_rejects_unknown_type():
    manager = XFCEManager(runner=lambda cmd, **kwargs: MagicMock(returncode=0, stdout="", stderr=""))

    with pytest.raises(ValueError):
        manager.set("xfwm4", "/general/foo", "bar", "object")


def test_snapshot_collects_channel_properties():
    outputs = {
        ("-c", "xfwm4", "-l"): "/general/theme\n/general/use_compositing\n",
        ("-c", "xfwm4", "-p", "/general/theme"): "Default\n",
        ("-c", "xfwm4", "-p", "/general/use_compositing"): "true\n",
    }

    def runner(cmd, **kwargs):
        key = tuple(cmd[1:])
        return MagicMock(returncode=0, stdout=outputs[key], stderr="")

    manager = XFCEManager(runner=runner)

    assert manager.snapshot(channels=["xfwm4"]) == {
        "xfwm4": {
            "/general/theme": "Default",
            "/general/use_compositing": "true",
        }
    }


def test_render_snapshot_text_is_stable():
    rendered = render_snapshot_text({"xfwm4": {"/b": "2", "/a": "1"}})
    assert rendered == "[xfwm4]\n  /a = 1\n  /b = 2"


def test_profile_plan_marks_changed_values():
    outputs = {
        ("-c", "xfwm4", "-p", "/general/use_compositing"): "true\n",
        ("-c", "xfwm4", "-p", "/general/prevent_focus_stealing"): "false\n",
        ("-c", "xfwm4", "-p", "/general/focus_new"): "true\n",
        ("-c", "xfwm4", "-p", "/general/mousewheel_rollup"): "true\n",
        ("-c", "xfwm4", "-p", "/general/scroll_workspaces"): "true\n",
        ("-c", "xfwm4", "-p", "/general/workspace_count"): "4\n",
        ("-c", "xsettings", "-p", "/Gtk/FontName"): "Sans 10\n",
        ("-c", "xsettings", "-p", "/Gtk/MonospaceFontName"): "Monospace 10\n",
        ("-c", "xsettings", "-p", "/Xft/DPI"): "96\n",
        ("-c", "xsettings", "-p", "/Net/EnableEventSounds"): "false\n",
        ("-c", "xsettings", "-p", "/Net/EnableInputFeedbackSounds"): "false\n",
    }

    def runner(cmd, **kwargs):
        return MagicMock(returncode=0, stdout=outputs[tuple(cmd[1:])], stderr="")

    manager = XFCEManager(runner=runner)
    plan = manager.profile_plan("memory-workstation")

    changed = {(item["channel"], item["property"]) for item in plan if item["changed"]}
    assert ("xfwm4", "/general/prevent_focus_stealing") in changed
    assert ("xfwm4", "/general/use_compositing") not in changed


def test_apply_profile_dry_run_does_not_set_values():
    calls = []

    def runner(cmd, **kwargs):
        calls.append(cmd)
        if "-p" in cmd and "-s" not in cmd:
            return MagicMock(returncode=0, stdout="old\n", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    manager = XFCEManager(runner=runner)
    plan = manager.apply_profile("memory-workstation", dry_run=True)

    assert plan
    assert not any("-s" in call for call in calls)


def test_apply_profile_sets_changed_values():
    calls = []
    current = {
        ("xfwm4", "/general/use_compositing"): "true",
        ("xfwm4", "/general/prevent_focus_stealing"): "false",
        ("xfwm4", "/general/focus_new"): "true",
        ("xfwm4", "/general/mousewheel_rollup"): "false",
        ("xfwm4", "/general/scroll_workspaces"): "false",
        ("xfwm4", "/general/workspace_count"): "4",
        ("xsettings", "/Gtk/FontName"): "Sans 10",
        ("xsettings", "/Gtk/MonospaceFontName"): "Monospace 10",
        ("xsettings", "/Xft/DPI"): "96",
        ("xsettings", "/Net/EnableEventSounds"): "false",
        ("xsettings", "/Net/EnableInputFeedbackSounds"): "false",
    }

    def runner(cmd, **kwargs):
        calls.append(cmd)
        if "-p" in cmd and "-s" not in cmd:
            channel = cmd[cmd.index("-c") + 1]
            prop = cmd[cmd.index("-p") + 1]
            return MagicMock(returncode=0, stdout=f"{current[(channel, prop)]}\n", stderr="")
        if "-s" in cmd:
            channel = cmd[cmd.index("-c") + 1]
            prop = cmd[cmd.index("-p") + 1]
            value = cmd[cmd.index("-s") + 1]
            current[(channel, prop)] = value
        return MagicMock(returncode=0, stdout="", stderr="")

    manager = XFCEManager(runner=runner)
    manager.apply_profile("memory-workstation")

    set_calls = [call for call in calls if "-s" in call]
    assert len(set_calls) == 2
    assert any("/general/prevent_focus_stealing" in call for call in set_calls)
    assert any("/Gtk/MonospaceFontName" in call for call in set_calls)


def test_4k_profile_targets_scaled_text_and_panel():
    outputs = {
        ("-c", "xfwm4", "-p", "/general/use_compositing"): "true\n",
        ("-c", "xfwm4", "-p", "/general/prevent_focus_stealing"): "true\n",
        ("-c", "xfwm4", "-p", "/general/focus_new"): "true\n",
        ("-c", "xfwm4", "-p", "/general/mousewheel_rollup"): "false\n",
        ("-c", "xfwm4", "-p", "/general/scroll_workspaces"): "false\n",
        ("-c", "xfwm4", "-p", "/general/workspace_count"): "4\n",
        ("-c", "xsettings", "-p", "/Gtk/FontName"): "Sans 10\n",
        ("-c", "xsettings", "-p", "/Gtk/MonospaceFontName"): "Monospace 11\n",
        ("-c", "xsettings", "-p", "/Gtk/CursorThemeSize"): "0\n",
        ("-c", "xsettings", "-p", "/Xft/DPI"): "96\n",
        ("-c", "xsettings", "-p", "/Net/EnableEventSounds"): "false\n",
        ("-c", "xsettings", "-p", "/Net/EnableInputFeedbackSounds"): "false\n",
        ("-c", "xfwm4", "-p", "/general/title_font"): "Sans Bold 9\n",
        ("-c", "xfce4-panel", "-p", "/panels/panel-1/size"): "26\n",
        ("-c", "xfce4-panel", "-p", "/panels/panel-1/icon-size"): "16\n",
        ("-c", "xfce4-panel", "-p", "/panels/panel-2/size"): "48\n",
    }

    def runner(cmd, **kwargs):
        return MagicMock(returncode=0, stdout=outputs[tuple(cmd[1:])], stderr="")

    manager = XFCEManager(runner=runner)
    plan = manager.profile_plan("memory-workstation-4k")

    targets = {(item["channel"], item["property"]): item["target"] for item in plan}
    assert targets[("xsettings", "/Xft/DPI")] == "144"
    assert targets[("xsettings", "/Gtk/FontName")] == "Sans 11"
    assert targets[("xfce4-panel", "/panels/panel-2/size")] == "64"


def test_state_summary_keeps_high_signal_keys_only():
    manager = XFCEManager(runner=lambda cmd, **kwargs: MagicMock(returncode=0, stdout="", stderr=""))
    summary = manager.state_summary(
        snapshot={
            "xsettings": {"/Xft/DPI": "144", "/Gtk/FontName": "Sans 11", "/unused": "x"},
            "xfwm4": {"/general/use_compositing": "true"},
        }
    )

    assert summary["xsettings"] == {"/Xft/DPI": "144", "/Gtk/FontName": "Sans 11"}
    assert summary["xfwm4"] == {"/general/use_compositing": "true"}


def test_write_and_read_xfce_cache(tmp_path):
    snapshot = {"xsettings": {"/Xft/DPI": "144"}}
    summary = {"xsettings": {"/Xft/DPI": "144"}}

    path = write_xfce_cache(tmp_path, snapshot, summary)
    payload = read_xfce_cache(tmp_path)

    assert path == tmp_path / "agent_context" / "xfce" / "latest.json"
    assert payload["summary"] == summary
    assert payload["snapshot"] == snapshot
    assert "generated_at" in payload


def test_sync_xfce_cache_writes_snapshot_and_summary(tmp_path):
    def runner(cmd, **kwargs):
        if cmd[1:] == ["-l"]:
            return MagicMock(returncode=0, stdout="Channels:\n  xsettings\n", stderr="")
        if cmd[1:] == ["-c", "xsettings", "-l"]:
            return MagicMock(returncode=0, stdout="/Xft/DPI\n", stderr="")
        if cmd[1:] == ["-c", "xsettings", "-p", "/Xft/DPI"]:
            return MagicMock(returncode=0, stdout="144\n", stderr="")
        raise AssertionError(cmd)

    manager = XFCEManager(runner=runner)
    path = sync_xfce_cache(tmp_path, manager)
    payload = read_xfce_cache(tmp_path)

    assert path.exists()
    assert payload["summary"] == {"xsettings": {"/Xft/DPI": "144"}}
    assert payload["snapshot"] == {"xsettings": {"/Xft/DPI": "144"}}


def test_apply_profile_refreshes_cache_after_mutation(tmp_path, monkeypatch):
    calls = []

    def runner(cmd, **kwargs):
        calls.append(cmd)
        if "-p" in cmd and "-s" not in cmd:
            channel = cmd[cmd.index("-c") + 1]
            prop = cmd[cmd.index("-p") + 1]
            values = {
                ("xfwm4", "/general/use_compositing"): "true",
                ("xfwm4", "/general/prevent_focus_stealing"): "false",
                ("xfwm4", "/general/focus_new"): "true",
                ("xfwm4", "/general/mousewheel_rollup"): "false",
                ("xfwm4", "/general/scroll_workspaces"): "false",
                ("xfwm4", "/general/workspace_count"): "4",
                ("xsettings", "/Gtk/FontName"): "Sans 10",
                ("xsettings", "/Gtk/MonospaceFontName"): "Monospace 10",
                ("xsettings", "/Gtk/CursorThemeSize"): "0",
                ("xsettings", "/Xft/DPI"): "96",
                ("xsettings", "/Net/EnableEventSounds"): "false",
                ("xsettings", "/Net/EnableInputFeedbackSounds"): "false",
                ("xfwm4", "/general/title_font"): "Sans Bold 9",
                ("xfce4-panel", "/panels/panel-1/size"): "26",
                ("xfce4-panel", "/panels/panel-1/icon-size"): "16",
                ("xfce4-panel", "/panels/panel-2/size"): "48",
            }
            return MagicMock(returncode=0, stdout=f"{values[(channel, prop)]}\n", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    manager = XFCEManager(runner=runner)
    manager.apply_profile("memory-workstation-4k")
    path = sync_xfce_cache(tmp_path, manager)

    assert path.exists()
    assert any("-s" in call for call in calls)


def test_diff_xfce_summaries_reports_only_changes():
    cached = {"xsettings": {"/Xft/DPI": "96", "/Gtk/FontName": "Sans 10"}}
    live = {"xsettings": {"/Xft/DPI": "144", "/Gtk/FontName": "Sans 10"}, "xfwm4": {"/general/use_compositing": "true"}}

    diff = diff_xfce_summaries(cached, live)
    assert diff == [
        {
            "channel": "xfwm4",
            "property": "/general/use_compositing",
            "cached": None,
            "live": "true",
            "changed": True,
        },
        {
            "channel": "xsettings",
            "property": "/Xft/DPI",
            "cached": "96",
            "live": "144",
            "changed": True,
        },
    ]


def test_render_summary_diff_text_handles_empty_and_nonempty():
    assert render_summary_diff_text([]) == "XFCE summary: no differences."
    rendered = render_summary_diff_text(
        [
            {
                "channel": "xsettings",
                "property": "/Xft/DPI",
                "cached": "96",
                "live": "144",
                "changed": True,
            }
        ]
    )
    assert rendered == "XFCE summary diff:\n- xsettings:/Xft/DPI '96' -> '144'"


def test_xfce_diff_falls_back_cleanly_when_live_state_unavailable(tmp_path, monkeypatch, capsys):
    class FakeManager:
        def state_summary(self):
            raise RuntimeError("Could not connect: Operation not permitted.")

    monkeypatch.setattr("memory_os.toolkit.xfce_manager.XFCEManager", lambda: FakeManager())

    cache_path = tmp_path / "agent_context" / "xfce" / "latest.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        '{"generated_at":"2026-07-02T00:00:00+00:00","summary":{"xsettings":{"/Xft/DPI":"96"}},"snapshot":{}}',
        encoding="utf-8",
    )

    args = argparse.Namespace(xfce_action="diff", json=False)
    code = cmd_xfce(args, MemoryOSConfig(config_path=str(tmp_path / "memory_os.config.json")))
    out = capsys.readouterr().out

    assert code == 1
    assert "XFCE live summary unavailable" in out
    assert "cached summary remains available" in out


def test_local_snapshot_parses_perchannel_xml(tmp_path, monkeypatch):
    xfconf_root = tmp_path / ".config" / "xfce4" / "xfconf" / "xfce-perchannel-xml"
    xfconf_root.mkdir(parents=True, exist_ok=True)
    (xfconf_root / "xsettings.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<channel name="xsettings" version="1.0">
  <property name="Xft" type="empty">
    <property name="DPI" type="int" value="144"/>
  </property>
  <property name="Gtk" type="empty">
    <property name="FontName" type="string" value="Sans 11"/>
  </property>
</channel>
""",
        encoding="utf-8",
    )

    monkeypatch.setattr("memory_os.toolkit.xfce_manager.Path.home", lambda: tmp_path)

    manager = XFCEManager(runner=lambda cmd, **kwargs: MagicMock(returncode=0, stdout="", stderr=""))
    assert manager.local_snapshot(channels=["xsettings"]) == {
        "xsettings": {"/Xft/DPI": "144", "/Gtk/FontName": "Sans 11"}
    }


def test_state_summary_falls_back_to_local_snapshot(tmp_path, monkeypatch):
    xfconf_root = tmp_path / ".config" / "xfce4" / "xfconf" / "xfce-perchannel-xml"
    xfconf_root.mkdir(parents=True, exist_ok=True)
    (xfconf_root / "xsettings.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<channel name="xsettings" version="1.0">
  <property name="Xft" type="empty">
    <property name="DPI" type="int" value="144"/>
  </property>
  <property name="Gtk" type="empty">
    <property name="FontName" type="string" value="Sans 11"/>
  </property>
</channel>
""",
        encoding="utf-8",
    )
    (xfconf_root / "xfwm4.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfwm4" version="1.0">
  <property name="general" type="empty">
    <property name="use_compositing" type="bool" value="true"/>
  </property>
</channel>
""",
        encoding="utf-8",
    )

    monkeypatch.setattr("memory_os.toolkit.xfce_manager.Path.home", lambda: tmp_path)

    manager = XFCEManager(runner=lambda cmd, **kwargs: MagicMock(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(manager, "snapshot", lambda channels=None: (_ for _ in ()).throw(RuntimeError("no live xfconf")))

    summary = manager.state_summary()
    assert summary == {
        "xsettings": {"/Xft/DPI": "144", "/Gtk/FontName": "Sans 11"},
        "xfwm4": {"/general/use_compositing": "true"},
    }
