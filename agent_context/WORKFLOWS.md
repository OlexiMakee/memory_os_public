# Workflows

Status: mandatory routing contract. Language: concise English.

Use one explicit workstream:
- `memory_os`: Memory OS core architecture, agent workflows, telemetry, retrieval logic, and framework self-improvement.

Naming guard: `memory_os` is the internal command/workflow alias for Memory OS. It is not related to the "Memos" note-taking application or the downstream "News Research Automation" product.

Accepted trigger forms:
- `memory_os nano`, `memory_os light mid`, `memory_os 6`, `memory_os giant`.

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
| 10 | big | strong cloud model | Full subsystem increment (e.g., retrieval logic). *Triggers SWARM_PROTOCOL.* |
| 11 | large | Claude/Gemini max | Architecture pass, staged plan. *Triggers SWARM_PROTOCOL.* |
| 12 | giant | Swarm Orchestrator | Repo-wide strategy. Maximize multi-agent delegation via `SWARM_PROTOCOL.md`. |

**Swarm Orchestration (L9-L12):**
- Tasks scored 9 to 12 MUST activate `agent_context/SWARM_PROTOCOL.md`.
- The active agent becomes the Orchestrator and delegates subtasks to other agents via `scripts/swarm_invoke.py`.
- Do not attempt linear execution for L11-L12 tasks.

Hard limits:
- Scores 1-5 must not change DB schema, add dependencies, or perform broad refactors.
- Scores 1-8 must stay inside current migration boundaries unless the user explicitly approves otherwise.
- Scores 9-12 may design schema/refactors, but must still ask before destructive actions, network-heavy operations, or secret handling.
- Local model experiments are allowed only for scores 1-3 and only on non-secret, low-risk text/code slices.

## Memory OS Workflow

Purpose: Improve the universal context graph and intelligence layer for the owner and agents.

Owns:
- Memory OS architecture, retrieval routing, memory snapshots (`nodes.jsonl`, `edges.jsonl`).
- CLI interface (`memory_os sync`, `query`, `backlinks`, `triage`).
- `roadmap.md`, `SWARM_PROTOCOL.md`, `AGENT_RULES.md`, `HANDSHAKE.md`.
- Telemetry, validation, compaction rules, and relation contracts.

Default constraints:
- Keep agent docs concise and operational.
- Do not store raw secrets or `.env` values in the graph.
- Prefer structural pointers (edges) over raw code chunks in memory.
- Separate durable rules from temporary handoff notes.

Typical tasks by score:
- 1 nano: add one handoff bullet; update a doc string.
- 2 micro: fix a bug in a single module (e.g., `MemoryCompactor.__init__`).
- 3 tiny: update one index pointer or add an assertion.
- 4 little: add one CLI command alias or task capsule validation logic.
- 5 pretty little: add one memory snapshot field or summary telemetry feature.
- 6 light mid: add one Memory OS CLI/API read path with focused tests.
- 7 mid: wire method-review/proposal generation into the graph.
- 8 high mid: implement retrieval-router exact lookup (FTS5) plus test fixtures.
- 9 mid high: integrate telemetry -> insight -> graph patch loops.
- 10 big: build a new Domain Adapter (e.g., `CodebaseDomainAdapter`).
- 11 large: design node/edge/event manifest lifecycle and validation states.
- 12 giant: repo-wide memory architecture audit and staged rebuild plan.
