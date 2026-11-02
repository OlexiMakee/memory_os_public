"""Project-local secret helpers.

These helpers only inspect or update the selected project's `.env`. They do not
read global credentials or copy secrets between workspaces.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path
from typing import Callable, Iterable, Optional, TextIO


TELEGRAM_ENV_KEYS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_API_ID", "TELEGRAM_API_HASH")


def _parse_env_lines(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def project_has_telegram_token(root: Path) -> bool:
    return bool(_parse_env_lines(Path(root) / ".env").get("TELEGRAM_BOT_TOKEN"))


def _validate_env_value(key: str, value: str) -> str:
    if not value or "\n" in value or "\r" in value:
        raise ValueError(f"{key} must be a non-empty single-line value")
    return value


def upsert_project_env(root: Path, key: str, value: str) -> None:
    env_path = Path(root) / ".env"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    replacement = f"{key}={_validate_env_value(key, value)}"
    for idx, raw in enumerate(lines):
        line = raw.strip()
        if line.startswith(f"{key}="):
            lines[idx] = replacement
            break
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(replacement)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_project_telegram_token(
    root: Path,
    *,
    interactive: bool,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
    prompt_fn: Optional[Callable[[str], str]] = None,
) -> bool:
    """Ensure selected project has an explicit Telegram bot token.

    Returns True when `.env` has TELEGRAM_BOT_TOKEN after the check. Empty input
    means "skip"; no token value is printed.
    """
    root = Path(root)
    if project_has_telegram_token(root):
        return True
    print(
        f"[telegram] {root}/.env has no TELEGRAM_BOT_TOKEN. "
        "Telegram daemon will not use any inherited global bot token for this workspace.",
        file=output_stream,
    )
    if not interactive:
        print(
            "Configure one with: memory_os workspace telegram-token "
            f"{root} --stdin < token.txt",
            file=output_stream,
        )
        return False
    prompt = prompt_fn or getpass.getpass
    try:
        token = prompt("Project TELEGRAM_BOT_TOKEN (blank to skip): ").strip()
    except (KeyboardInterrupt, EOFError):
        print("", file=output_stream)
        return False
    if not token:
        print("[telegram] skipped project Telegram bot token setup.", file=output_stream)
        return False
    upsert_project_env(root, "TELEGRAM_BOT_TOKEN", token)
    print(f"[telegram] wrote TELEGRAM_BOT_TOKEN to {root / '.env'}", file=output_stream)
    return True


def unset_shell_exports(keys: Iterable[str] = TELEGRAM_ENV_KEYS) -> str:
    return "unset " + " ".join(keys)
