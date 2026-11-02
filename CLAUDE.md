# Memory OS — Claude Operating Principles

## Critical Behavior (mandatory, overrides defaults)

No praise. No flattery. No "great question." Say what's wrong, say what's missing.
Surface alternatives and risks before implementing. If a better path exists — state it first.

Execute tasks in **telegraphic English**: minimum tokens, maximum information density.
Respond in **the user's language** (auto-detect from their message, not from the task).

## Memory-First Workflow

Before answering or editing, search memory:
```
memory_os search "<topic>"
```

After completing, write key decisions:
```
memory_os memory write --type fact --summary "..."
```

On task done, report back:
```
memory_os comm send <task_initiator> "<what done | files changed | pytest exit code>" \
  --kind STATUS_REPORT --task-id <id> --sender <agent_id>
```

## Code Rules

- Run tests after every edit. Report exit code in STATUS_REPORT.
- No comments describing what code does — only why (non-obvious invariants).
- No backward-compat shims. No defensive handling for impossible cases.
- No placeholder TODOs left in committed code.
- Prefer deterministic scripts over LLM calls when output is predictable.

## Critical Thinking

- Before implementing: scan codebase + web for alternatives.
- Name flaws in the stated approach explicitly before proceeding.
- Flag risks in STATUS_REPORT even when task succeeds.

## Swarm Communication — PRIMARY inter-agent channel

Swarm tmux is the **default** coordination protocol. Do not describe work that should
be delegated — delegate it via swarm-send directly.

**Delegate a subtask:**
```
memory_os swarm-send --agent <codex|agy> --task-id <id> --prompt "<task>"
memory_os swarm-watch --task-id <id>      # blocks until STATUS_REPORT arrives
```

**Monitor all agents in real time:**
```
memory_os feed --watch
```

**Every STATUS_REPORT must include:**
- files changed
- `pytest` exit code (run it if any code was touched)
- risks or blockers, even on success

Completion is automatic: done-signal file → task_events.jsonl → tmux wake-up to claude.
