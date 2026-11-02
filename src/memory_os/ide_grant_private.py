"""Personal, private-only CLI utility — never shipped to the public export.

Writes global Antigravity/Gemini permission grants to ~/.gemini/config/config.json.
This is deliberately excluded from the public repo via .gitattributes export-ignore;
cli.py imports it through a guarded try/except so the public build simply omits the
`ide-grant` subcommand instead of erroring.
"""

import argparse
from datetime import datetime
from pathlib import Path

from memory_os.core.config import MemoryOSConfig


def cmd_ide_grant(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    import json

    print("Configuring Antigravity Auto-Permissions...")
    home = Path.home()
    config_dir = home / ".gemini" / "config"
    config_path = config_dir / "config.json"

    print(f"Target config file: {config_path}")
    config_dir.mkdir(parents=True, exist_ok=True)

    wildcards = [
        "command(*)",
        "custom(*)",
        "execute_url(*)",
        "mcp(*)",
        "read_file(*)",
        "read_url(*)",
        "unsandboxed(*)",
        "write_file(*)"
    ]

    config_data = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    config_data = json.loads(content)
        except Exception as e:
            print(f"Warning: Failed to parse existing config.json: {e}")
            backup_path = config_path.with_name(f"config.json.bak-{datetime.now().strftime('%Y%m%d%H%M%S')}")
            try:
                config_path.rename(backup_path)
                print(f"Backup saved to: {backup_path}")
            except Exception as backup_err:
                print(f"Error: Could not back up config file: {backup_err}")
                return 1
            config_data = {}

    if "userSettings" not in config_data or not isinstance(config_data["userSettings"], dict):
        config_data["userSettings"] = {}
    if "globalPermissionGrants" not in config_data["userSettings"] or not isinstance(config_data["userSettings"]["globalPermissionGrants"], dict):
        config_data["userSettings"]["globalPermissionGrants"] = {}
    if "allow" not in config_data["userSettings"]["globalPermissionGrants"] or not isinstance(config_data["userSettings"]["globalPermissionGrants"]["allow"], list):
        config_data["userSettings"]["globalPermissionGrants"]["allow"] = []

    allow_list = config_data["userSettings"]["globalPermissionGrants"]["allow"]
    added_count = 0

    for wc in wildcards:
        if wc not in allow_list:
            allow_list.append(wc)
            print(f"Adding permission: {wc}")
            added_count += 1

    if added_count > 0:
        config_data["userSettings"]["globalPermissionGrants"]["allow"] = allow_list
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2)
            print("Successfully enabled auto-permissions! Antigravity will now run autonomously without prompting.")
            return 0
        except Exception as e:
            print(f"Error: Failed to write config.json: {e}")
            return 1
    else:
        print("All auto-permission wildcard rules are already configured in config.json.")
        return 0
