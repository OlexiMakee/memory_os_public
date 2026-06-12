# Agent Rules & Permissions

This file configures rules and whitelists commands for the Antigravity agent in the `memory_os` workspace.

## Allowed Commands
The following commands are whitelisted for execution without manual prompts:
- `python3`
- `PYTHONPATH=src python3`
- `python3 -m memory_os`
- `PYTHONPATH=src python3 -m memory_os`
- `python3 antigravity-permissions-grant/set_permissions.py`
- `python3 test_auto.py`
- `PYTHONPATH=src python3 test_auto.py`

## Directory Restrictions
- Do not modify files outside of the `memory_os` workspace root.
- Do not access or modify any credentials or secrets files.
