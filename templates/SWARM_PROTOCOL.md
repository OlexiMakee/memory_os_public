# Swarm Orchestration Protocol

Status: mandatory routing contract for L9-L12 tasks. Language: concise English.

## Overview
For complex tasks (Scores 9-12 in `WORKFLOWS.md`), the active agent becomes the
**Orchestrator** and delegates subtasks to **Worker** agents running in parallel.

## 1. Orchestrator Responsibilities
1. **Decomposition**: Break the task into independent, migration-safe subtasks (Scores 1-8).
2. **Registration**: Write each subtask into `swarm_backlog.json`.
3. **Invocation**: Use the wrapper script — never invoke agents manually via terminal:
   ```bash
   python scripts/swarm_invoke.py --target="claude" --task_id="subtask_123"
   ```
4. **Monitoring**: Track statuses in `swarm_backlog.json`:
   `pending` → `running` → `completed` / `failed` / `pending_limit`

## 2. Worker Invocation via `swarm_invoke.py`
The script handles:
- Background process spawning and output capture.
- **Rate Limit Trapping**: parks exhausted tasks as `pending_limit`, logs resumption time.
- **Graceful Failure**: prevents hallucinated terminal inputs.

## 3. Limit Handling
If a worker hits a rate limit:
- Mark as `pending_limit`, do NOT retry immediately.
- Move the Orchestrator to other parallel subtasks.
- Use `/schedule` or a sleep timer to resume when the limit resets.

## 4. Conflict Resolution
- Subtasks must be isolated by domain (Worker A owns `api/`, Worker B owns `ui/`).
- Only the Orchestrator merges results and updates `HANDSHAKE.md`.
- No two workers may modify the same file concurrently.

## 5. swarm_backlog.json Schema
```json
[
  {
    "task_id": "unique-id",
    "description": "what this worker must do",
    "score": 6,
    "status": "pending",
    "assigned_to": "claude",
    "files": ["path/to/file.py"]
  }
]
```
