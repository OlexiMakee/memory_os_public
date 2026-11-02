from __future__ import annotations

import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


XFCONF_TYPES = {"string", "int", "uint", "bool", "double"}


@dataclass
class XFCECommandResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


@dataclass(frozen=True)
class XFCEPropertyChange:
    channel: str
    property: str
    value: str
    value_type: str
    reason: str


MEMORY_WORKSTATION_PROFILE: List[XFCEPropertyChange] = [
    XFCEPropertyChange("xfwm4", "/general/use_compositing", "true", "bool", "Keep lightweight XFWM compositing enabled for smooth terminal/window rendering."),
    XFCEPropertyChange("xfwm4", "/general/prevent_focus_stealing", "true", "bool", "Keep agent terminals from losing focus to newly opened desktop windows."),
    XFCEPropertyChange("xfwm4", "/general/focus_new", "true", "bool", "Focus deliberate new windows immediately."),
    XFCEPropertyChange("xfwm4", "/general/mousewheel_rollup", "false", "bool", "Avoid accidental window roll-up while working in terminals."),
    XFCEPropertyChange("xfwm4", "/general/scroll_workspaces", "false", "bool", "Avoid accidental workspace switches from mouse wheel events."),
    XFCEPropertyChange("xfwm4", "/general/workspace_count", "4", "int", "Keep enough workspaces for agents, browser, logs, and scratch terminals."),
    XFCEPropertyChange("xsettings", "/Gtk/FontName", "Sans 10", "string", "Keep UI text compact and readable."),
    XFCEPropertyChange("xsettings", "/Gtk/MonospaceFontName", "Monospace 11", "string", "Make terminal-heavy work more readable."),
    XFCEPropertyChange("xsettings", "/Xft/DPI", "96", "int", "Use stable default DPI unless display inventory suggests otherwise."),
    XFCEPropertyChange("xsettings", "/Net/EnableEventSounds", "false", "bool", "Keep the workstation quiet during agent work."),
    XFCEPropertyChange("xsettings", "/Net/EnableInputFeedbackSounds", "false", "bool", "Keep the workstation quiet during repeated terminal input."),
]


MEMORY_WORKSTATION_4K_PROFILE: List[XFCEPropertyChange] = [
    *MEMORY_WORKSTATION_PROFILE[:6],
    XFCEPropertyChange("xsettings", "/Gtk/FontName", "Sans 11", "string", "Scale GTK text for a 4K display with a 1440p-like visual density."),
    XFCEPropertyChange("xsettings", "/Gtk/MonospaceFontName", "Monospace 12", "string", "Scale terminal text for a 4K display."),
    XFCEPropertyChange("xsettings", "/Gtk/CursorThemeSize", "32", "int", "Keep pointer visible on a 4K display."),
    XFCEPropertyChange("xsettings", "/Xft/DPI", "144", "int", "Use 1.5x text scale for a 4K display."),
    XFCEPropertyChange("xsettings", "/Net/EnableEventSounds", "false", "bool", "Keep the workstation quiet during agent work."),
    XFCEPropertyChange("xsettings", "/Net/EnableInputFeedbackSounds", "false", "bool", "Keep the workstation quiet during repeated terminal input."),
    XFCEPropertyChange("xfwm4", "/general/title_font", "Sans Bold 11", "string", "Scale window title text for a 4K display."),
    XFCEPropertyChange("xfce4-panel", "/panels/panel-1/size", "36", "int", "Scale the main panel for a 4K display."),
    XFCEPropertyChange("xfce4-panel", "/panels/panel-1/icon-size", "24", "int", "Scale main panel icons for a 4K display."),
    XFCEPropertyChange("xfce4-panel", "/panels/panel-2/size", "64", "int", "Scale the dock panel for a 4K display."),
]


XFCE_PROFILES = {
    "memory-workstation": MEMORY_WORKSTATION_PROFILE,
    "memory-workstation-4k": MEMORY_WORKSTATION_4K_PROFILE,
}


SUMMARY_KEYS = {
    "xsettings": [
        "/Xft/DPI",
        "/Gtk/FontName",
        "/Gtk/MonospaceFontName",
        "/Gtk/CursorThemeSize",
    ],
    "xfwm4": [
        "/general/theme",
        "/general/title_font",
        "/general/use_compositing",
        "/general/prevent_focus_stealing",
        "/general/workspace_count",
    ],
    "xfce4-panel": [
        "/panels/panel-1/size",
        "/panels/panel-1/icon-size",
        "/panels/panel-2/size",
        "/panels/dark-mode",
    ],
}


class XFCEManager:
    def __init__(self, runner=subprocess.run):
        self.runner = runner

    def available(self) -> bool:
        return shutil.which("xfconf-query") is not None

    def _run(self, args: List[str]) -> XFCECommandResult:
        res = self.runner(["xfconf-query", *args], capture_output=True, text=True)
        return XFCECommandResult(
            ok=res.returncode == 0,
            stdout=res.stdout.strip(),
            stderr=res.stderr.strip(),
            returncode=res.returncode,
        )

    def channels(self) -> List[str]:
        result = self._run(["-l"])
        if not result.ok:
            raise RuntimeError(result.stderr or "xfconf-query failed")
        lines = [line.strip() for line in result.stdout.splitlines()]
        return [line for line in lines if line and line != "Channels:"]

    def properties(self, channel: str) -> List[str]:
        result = self._run(["-c", channel, "-l"])
        if not result.ok:
            raise RuntimeError(result.stderr or f"cannot list XFCE channel: {channel}")
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def get(self, channel: str, prop: str) -> str:
        result = self._run(["-c", channel, "-p", prop])
        if not result.ok:
            raise RuntimeError(result.stderr or f"cannot read {channel}:{prop}")
        return result.stdout

    def set(self, channel: str, prop: str, value: str, value_type: str, create: bool = False) -> None:
        if value_type not in XFCONF_TYPES:
            raise ValueError(f"unsupported XFCE value type: {value_type}")
        args = ["-c", channel, "-p", prop, "-s", value, "-t", value_type]
        if create:
            args.append("-n")
        result = self._run(args)
        if not result.ok:
            raise RuntimeError(result.stderr or f"cannot set {channel}:{prop}")

    def reset(self, channel: str, prop: str, recursive: bool = False) -> None:
        args = ["-c", channel, "-p", prop, "-r"]
        if recursive:
            args.append("-R")
        result = self._run(args)
        if not result.ok:
            raise RuntimeError(result.stderr or f"cannot reset {channel}:{prop}")

    def profile_plan(self, profile: str) -> List[Dict[str, Any]]:
        changes = XFCE_PROFILES.get(profile)
        if changes is None:
            raise ValueError(f"unknown XFCE profile: {profile}")
        plan: List[Dict[str, Any]] = []
        for change in changes:
            try:
                current: Any = self.get(change.channel, change.property)
            except RuntimeError:
                current = None
            plan.append(
                {
                    "channel": change.channel,
                    "property": change.property,
                    "current": current,
                    "target": change.value,
                    "type": change.value_type,
                    "changed": current != change.value,
                    "reason": change.reason,
                }
            )
        return plan

    def apply_profile(self, profile: str, dry_run: bool = False) -> List[Dict[str, Any]]:
        changes = XFCE_PROFILES.get(profile)
        if changes is None:
            raise ValueError(f"unknown XFCE profile: {profile}")
        plan = self.profile_plan(profile)
        if dry_run:
            return plan
        for change, item in zip(changes, plan):
            if item["changed"]:
                self.set(change.channel, change.property, change.value, change.value_type, create=True)
        return self.profile_plan(profile)

    def snapshot(self, channels: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
        selected = channels or self.channels()
        data: Dict[str, Dict[str, Any]] = {}
        for channel in selected:
            data[channel] = {}
            for prop in self.properties(channel):
                try:
                    data[channel][prop] = self.get(channel, prop)
                except RuntimeError as exc:
                    data[channel][prop] = {"error": str(exc)}
        return data

    def local_snapshot(self, channels: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
        base = Path.home() / ".config" / "xfce4" / "xfconf" / "xfce-perchannel-xml"
        selected = channels or sorted(SUMMARY_KEYS)
        data: Dict[str, Dict[str, Any]] = {}
        for channel in selected:
            path = base / f"{channel}.xml"
            if not path.exists():
                continue
            tree = ET.parse(path)
            root = tree.getroot()
            data[channel] = {}

            def walk(node: ET.Element, prefix: str = "") -> None:
                name = node.get("name")
                if not name:
                    return
                prop_path = f"{prefix}/{name}"
                children = [child for child in node if child.tag == "property"]
                if children:
                    for child in children:
                        walk(child, prop_path)
                    return
                value_type = node.get("type", "")
                if value_type == "empty":
                    return
                value = node.get("value")
                if value is None and node.text:
                    value = node.text.strip() or None
                if value is not None:
                    data[channel][prop_path] = value

            for child in root:
                if child.tag == "property":
                    walk(child, "")
        return data

    def state_summary(self, snapshot: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Dict[str, Any]]:
        if snapshot is not None:
            data = snapshot
        else:
            try:
                data = self.snapshot(channels=sorted(SUMMARY_KEYS))
            except RuntimeError:
                data = self.local_snapshot(channels=sorted(SUMMARY_KEYS))
        summary: Dict[str, Dict[str, Any]] = {}
        for channel, props in SUMMARY_KEYS.items():
            channel_data = data.get(channel, {})
            reduced = {prop: channel_data.get(prop) for prop in props if prop in channel_data}
            if reduced:
                summary[channel] = reduced
        return summary


def xfce_cache_path(root: Path) -> Path:
    return root / "agent_context" / "xfce" / "latest.json"


def write_xfce_cache(root: Path, snapshot: Dict[str, Dict[str, Any]], summary: Dict[str, Dict[str, Any]]) -> Path:
    path = xfce_cache_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "snapshot": snapshot,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


def sync_xfce_cache(root: Path, manager: "XFCEManager") -> Path:
    try:
        snapshot = manager.snapshot()
    except RuntimeError:
        snapshot = manager.local_snapshot()
    summary = manager.state_summary(snapshot=snapshot)
    return write_xfce_cache(root, snapshot, summary)


def read_xfce_cache(root: Path) -> Dict[str, Any]:
    path = xfce_cache_path(root)
    if not path.exists():
        raise FileNotFoundError(f"XFCE cache not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def render_snapshot_text(snapshot: Dict[str, Dict[str, Any]]) -> str:
    lines: List[str] = []
    for channel in sorted(snapshot):
        lines.append(f"[{channel}]")
        props = snapshot[channel]
        if not props:
            lines.append("  (empty)")
            continue
        for prop in sorted(props):
            value = props[prop]
            if isinstance(value, (dict, list)):
                rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
            else:
                rendered = str(value)
            lines.append(f"  {prop} = {rendered}")
    return "\n".join(lines)


def render_profile_plan_text(profile: str, plan: List[Dict[str, Any]], dry_run: bool) -> str:
    mode = "dry-run" if dry_run else "applied"
    lines = [f"profile: {profile}", f"mode: {mode}"]
    for item in plan:
        marker = "change" if item["changed"] else "ok"
        current = "<missing>" if item["current"] is None else item["current"]
        lines.append(
            f"- [{marker}] {item['channel']}:{item['property']} "
            f"{current!r} -> {item['target']!r} ({item['type']})"
        )
        lines.append(f"  reason: {item['reason']}")
    return "\n".join(lines)


def render_summary_text(summary: Dict[str, Dict[str, Any]]) -> str:
    return render_snapshot_text(summary)


def diff_xfce_summaries(
    cached: Dict[str, Dict[str, Any]],
    live: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    channels = sorted(set(cached) | set(live))
    diff: List[Dict[str, Any]] = []
    for channel in channels:
        cached_props = cached.get(channel, {})
        live_props = live.get(channel, {})
        props = sorted(set(cached_props) | set(live_props))
        for prop in props:
            cached_value = cached_props.get(prop)
            live_value = live_props.get(prop)
            if cached_value != live_value:
                diff.append(
                    {
                        "channel": channel,
                        "property": prop,
                        "cached": cached_value,
                        "live": live_value,
                        "changed": True,
                    }
                )
    return diff


def render_summary_diff_text(diff: List[Dict[str, Any]]) -> str:
    if not diff:
        return "XFCE summary: no differences."
    lines = ["XFCE summary diff:"]
    for item in diff:
        cached = "<missing>" if item["cached"] is None else item["cached"]
        live = "<missing>" if item["live"] is None else item["live"]
        lines.append(f"- {item['channel']}:{item['property']} {cached!r} -> {live!r}")
    return "\n".join(lines)
