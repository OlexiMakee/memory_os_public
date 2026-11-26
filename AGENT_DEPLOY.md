# Agent Deployment Instructions For Memory OS

Use this document as the exact task prompt for a CLI agent on a clean Linux
server. The agent must execute commands, report failures with stdout/stderr, and
stop before destructive actions.

## Goal

Deploy Memory OS from GitHub on a clean Linux server, verify the memory engine,
and leave the machine ready for console-first agent work.

## GitHub Repository

Primary development repository:

```text
https://github.com/OlexiMakee/memory_os
```

If the repository is private, authenticate GitHub first using SSH or a GitHub
token. Do not paste tokens into shell history.

SSH alternative:

```text
git@github.com:OlexiMakee/memory_os.git
```

## Preconditions

- Linux server with shell access.
- `sudo` available for system packages, or preinstalled `git`, `curl`,
  `python3`, `python3-venv`, `python3-pip`, `sqlite3`.
- One CLI agent already installed and able to run shell commands.
- No requirement for a desktop environment.

## Deployment Steps

1. Inspect the host.

```bash
uname -a
cat /etc/os-release
python3 --version || true
git --version || true
```

2. Clone the repository.

```bash
git clone https://github.com/OlexiMakee/memory_os.git
cd memory_os
```

If HTTPS clone fails because the repository is private, use:

```bash
git clone git@github.com:OlexiMakee/memory_os.git
cd memory_os
```

3. Bootstrap the system.

For Ubuntu/Debian-like hosts where `sudo apt-get` is allowed:

```bash
bash scripts/bootstrap_ubuntu.sh --apt --extras dev,providers-ollama,resource-psutil
```

For hosts where system packages are already installed or sudo is unavailable:

```bash
bash scripts/bootstrap_ubuntu.sh --extras dev,providers-ollama,resource-psutil
```

4. Activate the environment.

```bash
source .venv/bin/activate
```

5. Run deterministic verification.

```bash
memory_os validate
python -m pytest tests/ -x -q
memory_os release-check --target private
memory_os resources snapshot
memory_os eval run retrieval-relevance
```

6. Check agent/runtime state.

```bash
memory_os workspace status
memory_os agent-manager --status
```

7. Optional: install and check local model runtime.

Only do this if the user explicitly wants local LLM support on this host:

```bash
bash scripts/bootstrap_ubuntu.sh --ollama --pull-model qwen2.5-coder:7b --extras providers-ollama
memory_os adapters audit
```

8. Optional: start console workspace.

```bash
memory_os zellij
```

If Zellij reports an exited/stale session:

```bash
memory_os workspace status
memory_os workspace clean-exited --runtime zellij --apply
memory_os zellij
```

## Success Criteria

- Repository is cloned and checked out on the target server.
- `.venv` exists and `memory_os` is available in that environment.
- `memory_os validate` passes.
- `python -m pytest tests/ -x -q` passes.
- `memory_os release-check --target private` returns `ok`.
- `memory_os eval run retrieval-relevance` passes.
- `memory_os agent-manager --status` runs and reports installed/missing agents.

## Failure Policy

- If a command fails, capture the exact command, exit code, and last 80 lines of
  output.
- Do not delete repository files to "fix" a failed install.
- Do not rotate or prune `memory/events.jsonl`; it is the audit source of truth.
- Do not install a desktop environment unless explicitly requested.
- Do not push changes back to GitHub unless explicitly instructed.

## Final Report Template

```text
Memory OS deployment report

Host:
- OS:
- Python:
- Repo path:
- Commit:

Verification:
- memory_os validate:
- pytest:
- release-check:
- retrieval-relevance:
- resources snapshot:
- agent-manager:

Notes:
- Missing optional agents:
- Missing optional adapters:
- Local model runtime:
- Blockers:
```
