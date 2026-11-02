import sys
import subprocess
from pathlib import Path
from unittest.mock import MagicMock
from memory_os.toolkit.linux_provisioner import LinuxProvisioner


def test_install_ui_already_installed(monkeypatch):
    provisioner = LinuxProvisioner(Path.cwd())
    
    # Mock subprocess.run for dpkg-query returning installed ok
    mock_run = MagicMock(returncode=0, stdout="install ok installed")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_run)

    assert provisioner.install_ui("kde") is True
    assert provisioner.install_ui("gnome") is True


def test_install_tool_already_installed(monkeypatch):
    provisioner = LinuxProvisioner(Path.cwd())

    # Mock shutil.which to find zellij
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/zellij" if cmd == "zellij" else None)

    assert provisioner.install_tool("zellij") is True


def test_install_ui_cancelled_by_user(monkeypatch):
    provisioner = LinuxProvisioner(Path.cwd())

    # Mock dpkg-query returning not installed
    mock_run = MagicMock(returncode=1, stdout="not-installed")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_run)

    # Mock user input choosing no 'n'
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    assert provisioner.install_ui("kde") is False


def test_install_ui_kde_runs_update_then_install(monkeypatch):
    provisioner = LinuxProvisioner(Path.cwd())
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["dpkg-query", "-W"]:
            return MagicMock(returncode=1, stdout="not-installed")
        return MagicMock(returncode=0, stdout="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    assert provisioner.install_ui("kde") is True
    assert ["sudo", "apt-get", "update"] in calls
    install_call = next(cmd for cmd in calls if cmd[:4] == ["sudo", "apt-get", "install", "-y"])
    assert "kde-plasma-desktop" in install_call
    assert "sddm" in install_call


def test_install_ui_set_boot_target(monkeypatch):
    provisioner = LinuxProvisioner(Path.cwd())

    # Case 1: already set
    mock_run_ok = MagicMock(returncode=0, stdout="graphical.target")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_run_ok)
    assert provisioner.install_ui("set-boot-target") is True

    # Case 2: not set, user cancels
    mock_run_multi = MagicMock(returncode=0, stdout="multi-user.target")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_run_multi)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert provisioner.install_ui("set-boot-target") is False

    # Case 3: not set, user authorizes
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd == ["systemctl", "get-default"]:
            return MagicMock(returncode=0, stdout="multi-user.target")
        return MagicMock(returncode=0)
        
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert provisioner.install_ui("set-boot-target") is True
    assert ["sudo", "systemctl", "set-default", "graphical.target"] in calls


def test_register_desktop_app_writes_launcher_and_refreshes_database(tmp_path, monkeypatch):
    provisioner = LinuxProvisioner(tmp_path)
    calls = []

    monkeypatch.setattr("memory_os.toolkit.linux_provisioner.Path.home", lambda: tmp_path)
    monkeypatch.setattr("memory_os.toolkit.linux_provisioner.shutil.which", lambda cmd: "/usr/bin/update-desktop-database" if cmd == "update-desktop-database" else None)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: calls.append(args[0]) or MagicMock(returncode=0))

    path = provisioner.register_desktop_app(
        "firefox",
        "Firefox",
        "/opt/firefox/firefox %u",
        comment="Web browser",
        icon="/opt/firefox/icon.png",
        categories="Network;WebBrowser;",
    )

    assert path == tmp_path / ".local" / "share" / "applications" / "firefox.desktop"
    text = path.read_text(encoding="utf-8")
    assert "Name=Firefox" in text
    assert "Exec=/opt/firefox/firefox %u" in text
    assert "Categories=Network;WebBrowser;" in text
    assert ["update-desktop-database", str(tmp_path / ".local" / "share" / "applications")] in calls


def test_install_app_firefox_registers_launcher(tmp_path, monkeypatch):
    provisioner = LinuxProvisioner(tmp_path)
    launcher_path = tmp_path / "firefox.desktop"
    mime_path = tmp_path / "mimeapps.list"
    monkeypatch.setattr(provisioner, "install_firefox_launcher", lambda: launcher_path)
    monkeypatch.setattr(provisioner, "set_default_browser", lambda desktop_id: mime_path)

    assert provisioner.install_app("firefox") is True


def test_set_default_browser_writes_mimeapps_list(tmp_path, monkeypatch):
    provisioner = LinuxProvisioner(tmp_path)
    monkeypatch.setattr("memory_os.toolkit.linux_provisioner.Path.home", lambda: tmp_path)
    monkeypatch.setattr("memory_os.toolkit.linux_provisioner.shutil.which", lambda cmd: None)

    path = provisioner.set_default_browser("firefox")

    assert path == tmp_path / ".config" / "mimeapps.list"
    text = path.read_text(encoding="utf-8")
    assert "x-scheme-handler/http=firefox.desktop;" in text
    assert "x-scheme-handler/https=firefox.desktop;" in text
    assert "text/html=firefox.desktop;" in text


def test_install_ui_sleep_management(monkeypatch):
    provisioner = LinuxProvisioner(Path.cwd())
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return MagicMock(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    assert provisioner.install_ui("disable-sleep") is True
    assert ["sudo", "systemctl", "mask", "sleep.target", "suspend.target", "hibernate.target", "hybrid-sleep.target"] in calls

    assert provisioner.install_ui("enable-sleep") is True
    assert ["sudo", "systemctl", "unmask", "sleep.target", "suspend.target", "hibernate.target", "hybrid-sleep.target"] in calls
