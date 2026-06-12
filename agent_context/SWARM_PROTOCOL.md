# Swarm Orchestration Protocol

Status: mandatory routing contract for L9-L12 tasks. Language: concise English.

## Overview
For complex tasks (Scores 9-12 in `WORKFLOWS.md`), the system transitions from linear execution to Swarm Orchestration. The active agent becomes the **Orchestrator** and delegates subtasks to **Worker** agents (e.g., Claude Code, Codex, Antigravity) running in parallel.

## 1. Orchestrator Responsibilities
1. **Decomposition:** Break the L9-L12 task into independent, migration-safe subtasks (Scores 1-8).
2. **Registration:** Write each subtask into `swarm_backlog.json` (located in the project root or managed via `scripts/swarm_sync.py`).
3. **Invocation:** DO NOT attempt to run terminal commands manually to invoke agents. Instead, use the deterministic wrapper script:
   ```bash
   python scripts/swarm_invoke.py \
     --target=claude \
     --task_id=subtask_123 \
     --prompt="implement X in src/module.py" \
     --model=sonnet \
     --workdir=/path/to/repo
   ```
   `--target` accepts `claude`, `agy`, or `codex`. `--model` and `--workdir` are optional; `--workdir` defaults to the current directory.
4. **Monitoring:** The Orchestrator can check `swarm_backlog.json` to track task statuses (`pending`, `running`, `completed`, `failed`, `pending_limit`).

## 2. Worker Invocation via `swarm_invoke.py`
The `swarm_invoke.py` script acts as a safety buffer between the Orchestrator and the terminal. It handles:
- Background process spawning.
- Output capturing and logging.
- **Rate Limit Trapping:** If the worker agent hits a rate limit or quota exhaustion, `swarm_invoke.py` intercepts the `stderr`, calculates the resumption time, sets a system timer, and safely parks the task in `pending_limit` status.
- **Graceful Failure:** Prevents hallucinated terminal inputs by containing the execution flow.

## 3. Limit Handling & Timers
If a worker hits a limit, the Orchestrator DOES NOT retry immediately.
- The wrapper script marks the task as `pending_limit`.
- The Orchestrator must move on to other parallel subtasks that do not require the exhausted model.
- Antigravity agents can use the `/schedule` tool or `schedule` slash command to sleep or wake up when the limit resets.

## 4. Conflict Resolution
- Subtasks must be isolated by domain (e.g., Worker A handles `api/`, Worker B handles `ui/`).
- Only the Orchestrator merges final results and updates `HANDSHAKE.md`.
- No two workers should modify the same file concurrently. The Orchestrator must enforce this when assigning subtasks.
