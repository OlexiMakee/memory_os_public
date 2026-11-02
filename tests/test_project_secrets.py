import argparse
import pytest

from memory_os.cli import cmd_workspace
from memory_os.core.config import MemoryOSConfig
from memory_os.toolkit.project_secrets import (
    ensure_project_telegram_token,
    project_has_telegram_token,
    upsert_project_env,
)


def test_project_telegram_token_prompt_writes_project_env(tmp_path):
    assert project_has_telegram_token(tmp_path) is False

    ok = ensure_project_telegram_token(
        tmp_path,
        interactive=True,
        prompt_fn=lambda _prompt: "123:abc",
    )

    assert ok is True
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN=123:abc" in env_text
    assert project_has_telegram_token(tmp_path) is True


def test_project_telegram_token_blank_prompt_does_not_write(tmp_path):
    ok = ensure_project_telegram_token(
        tmp_path,
        interactive=True,
        prompt_fn=lambda _prompt: "",
    )

    assert ok is False
    assert not (tmp_path / ".env").exists()


def test_upsert_project_env_replaces_existing_value(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("A=1\nTELEGRAM_BOT_TOKEN=old\nB=2\n", encoding="utf-8")

    upsert_project_env(tmp_path, "TELEGRAM_BOT_TOKEN", "new")

    assert env_path.read_text(encoding="utf-8").splitlines() == [
        "A=1",
        "TELEGRAM_BOT_TOKEN=new",
        "B=2",
    ]


def test_upsert_project_env_rejects_multiline_secret(tmp_path):
    with pytest.raises(ValueError):
        upsert_project_env(tmp_path, "TELEGRAM_BOT_TOKEN", "token\nEXTRA=bad")


def test_workspace_telegram_token_cli_reads_stdin(monkeypatch, tmp_path):
    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text('{"version": "0.1"}', encoding="utf-8")
    monkeypatch.setattr("sys.stdin.read", lambda: "token-from-stdin\n")
    args = argparse.Namespace(workspace_action="telegram-token", path=str(tmp_path), stdin=True, check=False)

    code = cmd_workspace(args, MemoryOSConfig(config_path=str(cfg_path)))

    assert code == 0
    assert "TELEGRAM_BOT_TOKEN=token-from-stdin" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_tmux_workspace_runtime_init_pane_unsets_telegram_env(monkeypatch, tmp_path):
    from memory_os.toolkit.workspace_runtime import TmuxWorkspaceRuntime

    calls = []
    runtime = TmuxWorkspaceRuntime()
    monkeypatch.setattr(runtime, "_tmux", lambda *args: calls.append(args))

    runtime._init_pane("session:agents.0", tmp_path, ["python", "-m", "memory_os"], "agent", venv=False)

    send_call = calls[0]
    assert send_call[:3] == ("send-keys", "-t", "session:agents.0")
    assert "unset TELEGRAM_BOT_TOKEN TELEGRAM_API_ID TELEGRAM_API_HASH" in send_call[3]
    assert f"cd {tmp_path}" in send_call[3]
