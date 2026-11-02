"""Declarative Linux environment provisioner for Memory OS.

Manages idempotent packages, user settings, Zellij, and DE (KDE/Gnome) setups on Ubuntu.
"""

import os
import sys
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple, Any


class LinuxProvisioner:
    def __init__(self, root: Path):
        self.root = root

    def _applications_dir(self) -> Path:
        return Path.home() / ".local" / "share" / "applications"

    def _desktop_entry_path(self, desktop_id: str) -> Path:
        return self._applications_dir() / f"{desktop_id}.desktop"

    def _write_desktop_entry(self, desktop_id: str, entry: Dict[str, str]) -> Path:
        path = self._desktop_entry_path(desktop_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["[Desktop Entry]", "Version=1.0", "Type=Application"]
        for key in ["Name", "Comment", "Exec", "Icon", "Terminal", "Categories", "StartupNotify"]:
            value = entry.get(key)
            if value is not None and value != "":
                lines.append(f"{key}={value}")
        lines.append("X-GNOME-Autostart-enabled=false")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def _refresh_desktop_database(self) -> None:
        if shutil.which("update-desktop-database") is None:
            return
        subprocess.run(["update-desktop-database", str(self._applications_dir())], check=False)

    def _mimeapps_path(self) -> Path:
        return Path.home() / ".config" / "mimeapps.list"

    def set_default_browser(self, desktop_id: str) -> Path:
        path = self._mimeapps_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                [
                    "[Default Applications]",
                    f"x-scheme-handler/http={desktop_id}.desktop;",
                    f"x-scheme-handler/https={desktop_id}.desktop;",
                    f"text/html={desktop_id}.desktop;",
                    "",
                    "[Added Associations]",
                    f"x-scheme-handler/http={desktop_id}.desktop;",
                    f"x-scheme-handler/https={desktop_id}.desktop;",
                    f"text/html={desktop_id}.desktop;",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        if shutil.which("update-desktop-database") is not None:
            subprocess.run(["update-desktop-database", str(self._applications_dir())], check=False)
        return path

    def register_desktop_app(
        self,
        desktop_id: str,
        name: str,
        exec_cmd: str,
        *,
        comment: str = "",
        icon: str = "",
        categories: str = "Utility;",
        terminal: bool = False,
    ) -> Path:
        entry = {
            "Name": name,
            "Comment": comment,
            "Exec": exec_cmd,
            "Icon": icon,
            "Terminal": "true" if terminal else "false",
            "Categories": categories,
            "StartupNotify": "true",
        }
        path = self._write_desktop_entry(desktop_id, entry)
        self._refresh_desktop_database()
        return path

    def install_firefox_launcher(self) -> Path:
        firefox_bin = Path("/opt/firefox/firefox")
        if not firefox_bin.exists():
            raise FileNotFoundError(f"Firefox binary not found: {firefox_bin}")
        icon = ""
        for candidate in [
            Path("/opt/firefox/browser/chrome/icons/default/default128.png"),
            Path("/opt/firefox/browser/chrome/icons/default/default256.png"),
        ]:
            if candidate.exists():
                icon = str(candidate)
                break
        return self.register_desktop_app(
            "firefox",
            "Firefox",
            f"{shlex.quote(str(firefox_bin))} %u",
            comment="Web browser",
            icon=icon,
            categories="Network;WebBrowser;",
            terminal=False,
        )

    def _package_installed(self, package: str) -> bool:
        res = subprocess.run(["dpkg-query", "-W", "-f=${Status}", package], capture_output=True, text=True)
        return "install ok installed" in res.stdout

    def run_command_with_guidance(self, desc: str, cmd: List[str], reason: str) -> bool:
        """Run system package commands with clear guidance and authorization."""
        print(f"\n🧠 [Memory OS Provisioner] — Action: {desc}")
        print(f"  Reason: {reason}")
        print(f"  Command: {shlex.join(cmd)}")
        print("  NOTE: This command requires administrator permissions and may prompt for password.")
        
        try:
            ans = input("Do you authorize memory_os to run this command? (y/n) [n]: ").strip().lower()
            if ans != "y":
                print("❌ Action cancelled by user.")
                return False
        except (KeyboardInterrupt, EOFError):
            print("\n❌ Action cancelled by user.")
            return False

        try:
            subprocess.run(cmd, check=True)
            print("✅ Action completed successfully!")
            return True
        except Exception as e:
            print(f"❌ Action failed: {e}")
            return False

    def install_ui(self, desktop: str) -> bool:
        """Idempotently install KDE Plasma or GNOME desktop environment, or configure boot target."""
        desktop = desktop.lower().strip()
        if desktop not in ("kde", "gnome", "set-boot-target", "disable-sleep", "enable-sleep"):
            print(f"Error: Unknown target '{desktop}'. Supported values: kde, gnome, set-boot-target, disable-sleep, enable-sleep.")
            return False

        if desktop == "disable-sleep":
            # 1. GNOME power settings (no sudo)
            if shutil.which("gsettings") is not None:
                subprocess.run(["gsettings", "set", "org.gnome.settings-daemon.plugins.power", "sleep-inactive-ac-type", "nothing"], check=False)
                subprocess.run(["gsettings", "set", "org.gnome.settings-daemon.plugins.power", "sleep-inactive-battery-type", "nothing"], check=False)
                print("🟢 Disabled sleep/suspend in GNOME power settings.")

            # 2. XFCE power settings (no sudo)
            if shutil.which("xfconf-query") is not None:
                subprocess.run(["xfconf-query", "-c", "xfce4-power-manager", "-p", "/xfce4-power-manager/inactivity-on-ac", "-s", "0"], check=False)
                subprocess.run(["xfconf-query", "-c", "xfce4-power-manager", "-p", "/xfce4-power-manager/inactivity-on-battery", "-s", "0"], check=False)
                print("🟢 Disabled inactivity sleep/suspend in XFCE power manager.")

            desc = "Disable automatic system sleep/suspend (systemd)"
            cmd = ["sudo", "systemctl", "mask", "sleep.target", "suspend.target", "hibernate.target", "hybrid-sleep.target"]
            reason = "Prevent the system from suspending/sleeping at the system level (requires sudo)."
            return self.run_command_with_guidance(desc, cmd, reason)

        if desktop == "enable-sleep":
            # Restore default GNOME/XFCE settings if possible
            if shutil.which("gsettings") is not None:
                subprocess.run(["gsettings", "set", "org.gnome.settings-daemon.plugins.power", "sleep-inactive-ac-type", "suspend"], check=False)
                print("🟢 Restored GNOME sleep/suspend power settings.")

            desc = "Enable system sleep/suspend (systemd)"
            cmd = ["sudo", "systemctl", "unmask", "sleep.target", "suspend.target", "hibernate.target", "hybrid-sleep.target"]
            reason = "Restore standard system sleep/suspend behavior at the system level (requires sudo)."
            return self.run_command_with_guidance(desc, cmd, reason)

        if desktop == "set-boot-target":
            res = subprocess.run(["systemctl", "get-default"], capture_output=True, text=True)
            if "graphical.target" in res.stdout:
                print("🟢 Default boot target is already set to graphical.target.")
                return True

            desc = "Set default systemd boot target to graphical"
            cmd = ["sudo", "systemctl", "set-default", "graphical.target"]
            reason = "Configuring the system to boot directly into the graphical desktop user interface (GUI)."
            return self.run_command_with_guidance(desc, cmd, reason)

        if desktop == "kde":
            packages = ["kde-plasma-desktop", "sddm", "plasma-nm", "konsole", "dolphin", "systemsettings"]
            if self._package_installed("plasma-desktop") or self._package_installed("kde-plasma-desktop"):
                print("🟢 KDE Plasma is already installed on this machine.")
                return True

            if not self.run_command_with_guidance(
                "Update APT package index",
                ["sudo", "apt-get", "update"],
                "Fresh package metadata reduces install failures for KDE Plasma dependencies.",
            ):
                return False

            desc = "Install KDE Desktop Environment"
            cmd = ["sudo", "apt-get", "install", "-y", *packages]
            reason = "KDE Plasma and SDDM are required for a local graphical Memory OS development workspace."
            return self.run_command_with_guidance(desc, cmd, reason)

        elif desktop == "gnome":
            res = subprocess.run(["dpkg-query", "-W", "-f='${Status}'", "gnome-shell"], capture_output=True, text=True)
            if "install ok installed" in res.stdout:
                print("🟢 GNOME Shell (gnome-shell) is already installed on this machine.")
                return True

            desc = "Install GNOME Desktop Environment"
            cmd = ["sudo", "apt-get", "install", "-y", "gdm3", "gnome-shell", "gnome-session"]
            reason = "GNOME Desktop Environment is required for launching the GNOME GUI. We will also install GDM3 display manager."
            return self.run_command_with_guidance(desc, cmd, reason)

        return False

    def install_tool(self, tool: str) -> bool:
        """Idempotently install Zellij multiplexer or other terminal tools."""
        tool = tool.lower().strip()
        if tool != "zellij":
            print(f"Error: Unknown tool '{tool}'. Supported values: zellij.")
            return False

        if shutil.which("zellij") is not None:
            print("🟢 Zellij terminal multiplexer is already installed and available in PATH.")
            return True

        # Check if cargo is available to build, or download latest binary
        if shutil.which("cargo") is not None:
            desc = "Install Zellij via cargo"
            cmd = ["cargo", "install", "--locked", "zellij"]
            reason = "Compiling Zellij from source using Rust cargo build system."
            return self.run_command_with_guidance(desc, cmd, reason)
        else:
            # Fallback to snap or curl binary download
            desc = "Install Zellij via Snap Package Manager"
            cmd = ["sudo", "snap", "install", "zellij", "--classic"]
            reason = "Zellij is required for launching the modern Zellij agent workspace backend."
            return self.run_command_with_guidance(desc, cmd, reason)

        return False

    def install_app(self, app: str) -> bool:
        app = app.lower().strip()
        if app != "firefox":
            print(f"Error: Unknown app '{app}'. Supported values: firefox.")
            return False
        try:
            path = self.install_firefox_launcher()
            mime_path = self.set_default_browser("firefox")
        except Exception as exc:
            print(f"Error: {exc}")
            return False
        print(f"🟢 Firefox launcher registered: {path}")
        print(f"🟢 Default browser updated: {mime_path}")
        return True


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 -m memory_os.toolkit.linux_provisioner <action> <target>")
        print("Examples:")
        print("  python3 -m memory_os.toolkit.linux_provisioner ui kde")
        print("  python3 -m memory_os.toolkit.linux_provisioner tool zellij")
        print("  python3 -m memory_os.toolkit.linux_provisioner app firefox")
        sys.exit(1)

    action = sys.argv[1]
    target = sys.argv[2]
    root = Path(__file__).resolve().parents[3]
    provisioner = LinuxProvisioner(root)

    if action == "ui":
        ok = provisioner.install_ui(target)
    elif action == "tool":
        ok = provisioner.install_tool(target)
    elif action == "app":
        ok = provisioner.install_app(target)
    else:
        print(f"Unknown action '{action}'")
        ok = False

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
