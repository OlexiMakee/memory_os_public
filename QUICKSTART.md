# Memory OS Quickstart

This is the short path for a clean Linux server or VM. For a full agent handoff
prompt, use [AGENT_DEPLOY.md](AGENT_DEPLOY.md).

## 1. Clone

Use the GitHub URL you were given. For the private development repository:

```bash
git clone https://github.com/OlexiMakee/memory_os.git
cd memory_os
```

If HTTPS is not authenticated for the private repository, use SSH instead:

```bash
git clone git@github.com:OlexiMakee/memory_os.git
cd memory_os
```

## 2. Bootstrap

On Ubuntu/Debian-like servers:

```bash
bash scripts/bootstrap_ubuntu.sh --apt --extras dev,providers-ollama,resource-psutil
```

This installs system packages only when `--apt` is present, creates `.venv`,
installs Memory OS in editable mode, and runs deterministic checks.

Optional local model runtime:

```bash
bash scripts/bootstrap_ubuntu.sh --ollama --pull-model qwen2.5-coder:7b --extras providers-ollama
```

## 3. Verify

```bash
source .venv/bin/activate
memory_os validate
memory_os release-check --target private
memory_os resources snapshot
memory_os agent-manager --status
```

Expected result:

- `validate` passes.
- `release-check --target private` returns `ok`.
- `resources snapshot` reports resource level `COOL` unless the host is out of disk.
- `agent-manager --status` shows installed CLI agents and their runtime status.

## 4. Start The Workspace

For the console-first multi-agent workspace:

```bash
memory_os zellij
```

If a previous Zellij session is stale:

```bash
memory_os workspace status
memory_os workspace clean-exited --runtime zellij --apply
memory_os zellij
```

## 5. Agent Rule

Add this to the active agent instructions:

```markdown
Before work: run `memory_os search "<topic>"`.
After code edits: run `python -m pytest tests/ -x -q`.
Before publishing: run `memory_os release-check --target private`.
After finishing a swarm task: send `memory_os comm send --kind STATUS_REPORT ...`.
```

## 6. Minimal Health Probe

```bash
memory_os search "memory graph"
memory_os eval run retrieval-relevance
memory_os storage advise
```

If all three commands work, the memory engine, retrieval eval loop, and storage
advisor are usable on the new machine.
