---
name: swarm-runtime-hygiene
description: Diagnose and harden Memory OS swarm runtime, agent-manager, daemon housekeeping, Telegram relay, zellij/tmux/herdr backends, quota state, and stuck task cleanup.
allowed-tools:
  - shell
  - git
---

# Swarm Runtime Hygiene

Use this skill inside the Memory OS repository when agents, Telegram, quota timers, zellij panes, or daemon health look inconsistent.

Initial checks:

```bash
python3 -m memory_os comm status
python3 -m memory_os agent-manager --status
python3 -m memory_os workspace status
python3 -m memory_os doctor
```

Prefer backend state over screen scraping:

1. Read daemon snapshots: `agent_context/agents/runtime_health.json`, `relay_watch.json`, quota state.
2. Use live pane scraping only as fallback, and record when sandboxed CLI context blocks zellij actions.
3. Check task leases, stale Telegram chat tasks, inbox cursors, and `comm.failed` events before assuming delivery worked.
4. Keep runtime interfaces backend-agnostic: workspace/session, pane, agent-status, event stream, restore, send-input, read-output.
5. Do not hard-code zellij-only semantics outside the zellij runtime adapter.

After edits, run targeted tests first, then:

```bash
python3 -m pytest tests/ -x -q
```
