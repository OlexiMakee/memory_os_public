# Memory OS — Agent Operating Principles
# Read by: Codex CLI, Antigravity (agy), any OpenAI-compatible agent CLI.

## Critical Behavior (mandatory, overrides defaults)

No praise. No flattery. Say what's wrong, say what's missing.
Surface alternatives and risks before implementing. If a better path exists — state it first.

Execute tasks in **telegraphic English**: minimum tokens, maximum information density.
Respond in **the user's language** (auto-detect from their message, not from the task).

## Memory-First Workflow

Before answering or editing, search memory:
```
memory_os search "<topic>"
```

On task done, report back via swarm:
```
memory_os comm send --kind STATUS_REPORT --sender <agent_id> --task-id <id> \
  <task_initiator> "<what done | files changed | pytest exit code>"
```

## Code Review Rules

Every code change and review MUST verify and cite the following stable rule IDs:

- **[CR-TESTS]**: Run `python -m pytest tests/ -x -q` after every edit. 0 failures allowed.
- **[CR-GATES]**: Run `memory_os release-check --target private`. All AST gates and boundaries (`architecture.toml` canonical modules) must pass.
- **[CR-GRAPH]**: Graph writes must occur only through `RelationPatchStore`-backed API. Retain audit events.
- **[CR-CONTRACT]**: Preserve CLI flags/exit codes, comm wire states, and config schemas unless explicit migration. Prefer deterministic scripts over LLM calls when output is predictable.
- **[CR-RUNTIME]**: No raw zellij/tmux/provider/pane assumptions outside runtime/registry boundaries.
- **[CR-STYLE]**: No comments describing what code does — only why. No unwired/speculative adapters. No backward-compat shims. No defensive handling for impossible cases. No bare excepts.
- **[CR-CITATION]**: Review STATUS_REPORTs must cite rule IDs (e.g. `[CR-TESTS]`, `[CR-CONTRACT]`) or state `[judgment call]`. Findings format: `severity | file:line | rule_id | impact | safe_fix`.

## Critical Thinking

- Before implementing: scan codebase + web for alternatives.
- Name flaws explicitly before proceeding.
- Flag risks in STATUS_REPORT even when task succeeds.

## /teamwork — agy Multi-Agent Mode

Use `/teamwork` or `/teamwork-preview` when a task requires parallel exploration + implementation:
- `/teamwork-preview` — dry-run: decomposes into milestones, produces plan.md without executing
- `/teamwork` — full execution: spawns orchestrator + sentinel + explorers + workers

**When to use /teamwork:**
- Multi-file refactoring across 5+ modules
- Tasks with distinct explore-then-implement phases
- Audit + implementation pairs (explorers find, workers fix)

**Structure your /teamwork request:**
```
/teamwork
<clear task description>

Requirements:
- R1. <what to build>
- R2. <constraints>

Acceptance Criteria:
- [ ] All tests pass: python -m pytest tests/ -x -q
- [ ] STATUS_REPORT sent to task initiator via: memory_os comm send ...
```

**Victory audit is mandatory** — sentinel gates completion.
**Always end with STATUS_REPORT** to task initiator via swarm.

Agent directories: `.agents/<role>/` — read handoff.md for results.

## Swarm Communication — PRIMARY inter-agent channel

Swarm AgentComm is the **default** coordination protocol. tmux is only one optional
transport/runtime. Do not describe work that should be delegated — delegate it via
swarm-send directly.

**Report completion to task initiator — mandatory after every task:**
```
memory_os comm send --kind STATUS_REPORT --sender <agent_id> \
  --task-id <id> <task_initiator> "<files changed | pytest N passed | risks>"
```

**Delegate a subtask to another agent:**
```
memory_os swarm-send --agent <target_agent> --task-id <id> --prompt "<task>"
```

**Monitor all agents:**
```
memory_os feed --watch
```

Rules:
- On incoming wake-up or notification: immediately inspect inbox (`memory_os comm inbox`) and process tasks without delay.
- Always wrap outgoing inter-agent communication messages with structural protocol tags (`[SWARM MESSAGE ...]` and `[END SWARM MESSAGE]`).
- **Reporting Inaccuracies**: Whenever an inaccuracy, discrepancy, or flaw is detected, ALWAYS report it back via `memory_os comm send` to the initiating agent or orchestrator.
- Never leave a task without sending STATUS_REPORT. Even failed tasks must report.
- Always run `python -m pytest tests/ -x -q` before STATUS_REPORT if code was touched.
- Include risks and blockers in STATUS_REPORT even on success.

## Allowed Commands (agy whitelist)

- `python3`, `PYTHONPATH=src python3`
- `python3 -m memory_os`, `PYTHONPATH=src python3 -m memory_os`
- `python3 -m pytest`, `pytest`
- `git status`, `git diff`, `git add`, `git commit`

## Directory Restrictions

- Do not modify files outside the `memory_os` workspace root.
- Do not access or modify credentials or secrets files.

<!-- MEMORY_OS SKILLS BLOCK START (auto-generated, do not edit by hand) -->
## Available Agent Skills

You have access to the following repo-local skill packs under `skills/`:
- **memory-backend-audit**: Audit and improve Memory OS memory backend quality: patch-store write path, lifecycle gates, retrieval evals, deduplication, timecodes, and graph health. Use for backend-first memory work before UI work.
- **plan**: Write concrete, actionable implementation plans in markdown.
- **release-roadmap-audit**: Audit Memory OS roadmap, docs, changelog-like summaries, commits, and release readiness by comparing shipped code against documented strategy and user-facing CLI behavior.
- **requesting-code-review**: Pre-commit verification checklist: security scan, quality gates, and self-review.
- **simplify-code**: Review and simplify recent code changes for reuse, quality, and efficiency.
- **skill-pack-maintainer**: Maintain Memory OS skill packs under skills/.
- **solid-unix-portability-audit**: Audit Memory OS changes for SOLID boundaries, Unix-style CLI contracts, deterministic automation, and Linux/macOS portability before implementation or review.
- **swarm-runtime-hygiene**: Diagnose and harden Memory OS swarm runtime, agent-manager, daemon housekeeping, Telegram relay, zellij/tmux/herdr backends, quota state, and stuck task cleanup.
- **systematic-debugging**: 4-phase root cause debugging. Understand bugs before fixing.

To check, sync, or lock skills, use `memory_os skills` commands.
<!-- MEMORY_OS SKILLS BLOCK END -->
