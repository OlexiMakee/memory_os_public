# VS Code Remote-SSH to `memoryos`

Connect VS Code (running on the Mac) to the Ubuntu workstation and edit
`~/dev/memory_os` directly on that machine, with no local copy or sync step.

## Target host

- SSH alias: `memoryos`
- Tailscale IP: `100.87.69.110`
- LAN IP: `192.168.0.190`
- Remote user: `oleksii`
- Repo path on host: `/home/oleksii/dev/memory_os`

## 1. Install the Remote-SSH extension

In VS Code, open Extensions (`Cmd+Shift+X`) and install:

```text
ms-vscode-remote.remote-ssh
```

(Search for "Remote - SSH" by Microsoft if installing by hand.)

## 2. Add a Host entry

Add the host to your local `~/.ssh/config` on the Mac (skip if `memoryos`
already resolves via `ssh memoryos`):

```text
Host memoryos
    HostName 100.87.69.110
    User oleksii
    # Fallback if Tailscale is down:
    # HostName 192.168.0.190
```

Verify from a terminal before using VS Code:

```bash
ssh memoryos 'hostname; whoami'
```

Expected: `memoryos` / `oleksii`.

## 3. Connect from VS Code

1. `Cmd+Shift+P` → `Remote-SSH: Connect to Host...`
2. Select `memoryos`.
3. A new VS Code window opens, connected to the remote host (status bar
   bottom-left shows `SSH: memoryos`).

## 4. Open the repo folder

In the remote window: `File > Open Folder...` → enter or browse to:

```text
/home/oleksii/dev/memory_os
```

## 5. Select the Python interpreter

The repo already has a provisioned virtualenv at `.venv`. Once the folder is
open:

1. `Cmd+Shift+P` → `Python: Select Interpreter`.
2. Choose `Enter interpreter path...` if it's not auto-detected, and enter:

```text
./.venv/bin/python
```

This resolves to `/home/oleksii/dev/memory_os/.venv/bin/python` on the
remote host. Confirm in a VS Code terminal (which opens remote by default):

```bash
which python3 && python3 --version
```

## 6. Recommended extensions (install on the remote host)

Remote-SSH installs extensions separately per host. When prompted, or
manually via Extensions panel (it will show a "Local - Installed" vs
"SSH: memoryos - Installed" split), install on the remote side:

- `ms-python.python` (Python)
- `ms-python.vscode-pylance` (Pylance)

## Notes

- Do not SSH from the Ubuntu host back into itself; this workflow is for
  connecting from the Mac only.
- If Tailscale is down, swap `HostName` to the LAN IP `192.168.0.190` (only
  reachable when both machines are on the same local network).
