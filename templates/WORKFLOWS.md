# Workflows

Status: mandatory routing contract. Language: concise English.

Use one explicit workstream per project. Define it below and use it as a trigger prefix
when invoking agents (e.g. `myproject nano`, `myproject giant`).

Workstream: `[YOUR_PROJECT_ALIAS]` — [one-line description of scope]

## 12-Step Scale

| Score | Name | Model Fit | Scope |
|---:|---|---|---|
| 1 | nano | weakest local/small model | Read one short file, answer one fact, fix one typo, add one TODO. |
| 2 | micro | weak local/small model | Inspect one symbol or log slice, make one-line safe edit, no architecture. |
| 3 | tiny | local/free small model | Small localized patch, one assertion, one doc bullet. |
| 4 | little | local/free stronger model | One helper/function, one compact test, narrow docs update. |
| 5 | pretty little | small cloud/free model | One cohesive behavior in one module, focused tests. |
| 6 | light mid | Codex low/medium | One endpoint/service bridge or read path. |
| 7 | mid | Codex medium | One feature slice across 2-4 files with tests and handoff update. |
| 8 | high mid | Codex high | Multi-file feature slice, tests, docs, migration-safe integration. |
| 9 | mid high | strong cloud model | Cross-module integration. *Triggers SWARM_PROTOCOL.* |
| 10 | big | strong cloud model | Full subsystem increment. *Triggers SWARM_PROTOCOL.* |
| 11 | large | Claude/Gemini max | Architecture pass, staged plan. *Triggers SWARM_PROTOCOL.* |
| 12 | giant | Swarm Orchestrator | Repo-wide strategy. Maximize multi-agent delegation via `SWARM_PROTOCOL.md`. |

**Swarm Orchestration (L9-L12):**
- Tasks scored 9–12 MUST activate `agent_context/SWARM_PROTOCOL.md`.
- The active agent becomes the Orchestrator and delegates subtasks to worker agents.
- Do not attempt linear execution for L11-L12 tasks.

Hard limits:
- Scores 1-5: no DB schema changes, no new dependencies, no broad refactors.
- Scores 1-8: stay inside current migration boundaries unless user explicitly approves.
- Scores 9-12: may design schema/refactors, but must ask before destructive actions.

## Project Workflow

Purpose: [what agents are optimizing for in this project]

Owns:
- [area of ownership]
- [area of ownership]

Default constraints:
- [key constraint]
- [key constraint]
- For non-trivial feature work, keep `spec.md`, `plan.md`, `tasks.md`, and verification evidence traceable.

Typical tasks by score:
- 1 nano: [example]
- 4 little: [example]
- 7 mid: [example]
- 12 giant: [example]
