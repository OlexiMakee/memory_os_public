# Workflows

Status: mandatory routing contract. Language: concise English.

Use two explicit workstreams:
- `product`: client-facing Governed Autonomous Intelligence Workspace.
- `memory_os`: Memory OS, agent workflow, development telemetry, repo analysis, and self-improvement tools.

Naming guard: `memory_os` is an internal command/workflow alias for Memory OS. It is
not the final public product name and is unrelated to the existing Memos
note-taking application.

Accepted trigger forms:
- `product nano`, `product mid step`, `product 8`, `product giant steps`.
- `memory_os nano`, `memory_os light mid`, `memory_os 6`, `memory_os giant`.
- If no workflow is named, infer from the task. If inference is mixed, update `HANDSHAKE.md` and finish the smaller blocking side first.

## 12-Step Scale

| Score | Name | Model Fit | Scope |
|---:|---|---|---|
| 1 | nano | weakest local/small model | Read one short file, answer one fact, fix one typo, add one TODO. |
| 2 | micro | weak local/small model | Inspect one symbol or log slice, make one-line safe edit, no architecture. |
| 3 | tiny | local/free small model | Small localized patch, one assertion, one route smoke, one doc bullet. |
| 4 | little | local/free stronger model | One helper/function, one compact test, narrow docs update. |
| 5 | pretty little | small cloud/free model | One cohesive behavior in one module, focused tests. |
| 6 | light mid | Codex low/medium | One endpoint/service bridge or one UI panel state, no schema change. |
| 7 | mid | Codex medium | One feature slice across 2-4 files with tests and handoff update. |
| 8 | high mid | Codex high | Multi-file feature slice, tests, docs, migration-safe integration. |
| 9 | mid high | strong cloud model | Cross-module integration. *Triggers SWARM_PROTOCOL.* |
| 10 | big | strong cloud model | Full subsystem increment (API+UI). *Triggers SWARM_PROTOCOL.* |
| 11 | large | Claude/Gemini max | Architecture pass, staged plan. *Triggers SWARM_PROTOCOL.* |
| 12 | giant | Swarm Orchestrator | Repo-wide strategy. Maximize multi-agent delegation via `SWARM_PROTOCOL.md`. |

**Swarm Orchestration (L9-L12):**
- Tasks scored 9 to 12 MUST activate `agent_context/SWARM_PROTOCOL.md`.
- The active agent becomes the Orchestrator and delegates subtasks to Claude/Codex via `scripts/swarm_invoke.py`.
- Do not attempt linear execution for L11-L12 tasks.

Hard limits:
- Scores 1-5 must not change DB schema, add dependencies, or perform broad refactors.
- Scores 1-8 must stay inside current migration boundaries unless the user explicitly approves otherwise.
- Scores 9-12 may design schema/refactors, but must still ask before destructive actions, live migrations, paid/network-heavy operations, or secret handling.
- Local model experiments are allowed only for scores 1-3 and only on non-secret, low-risk text/code slices.

## Product Workflow

Purpose: make the customer-facing workspace useful, governed, and shippable.

Owns:
- Editorial MVP, dashboard UX, briefs, source citations.
- Source Registry UI, ingestion connectors, OCR/transcripts.
- Topic analytics, anomalies, entity tracking, timelines.
- Evidence/OSINT mode, exports, watchers, review queues.
- RBAC and operator panels that affect customer workflows.

Default constraints:
- Preserve governance source tiers A/B/C/D/E/X.
- No live DB migration without explicit user approval.
- Prefer migration-safe preview/API bridges before persistence.
- UI click-through remains manual unless browser automation is requested or necessary.

Typical tasks by score (Memos):
- 1 nano: read one config file; add one TODO to HANDSHAKE; classify one blocking issue.
- 2 micro: inspect one memory file; add one-line safe timestamp; update one TODO status.
- 3 tiny: add one lifecycle event entry; fix one JSON schema example; validate one audit log.
- 4 little: add one audit report section; consolidate one decision table; merge one decision log.
- 5 pretty little: build one Memory OS utility (audit/validate/snapshot); add focused tests.
- 6 light mid: add migration-safe preview endpoint or read-only UI panel.
- 7 mid: wire API + service + focused tests for one product capability.
- 8 high mid: connect one analytics primitive to briefs/widgets without schema mutation.
- 9 mid high: integrate source registry flow across UI/API/service with compatibility guards.
- 10 big: complete an Editorial MVP workflow from ingestion preview to source-backed brief.
- 11 large: design governance migration and rollout plan with rollback/test matrix.
- 12 giant: restructure product roadmap or build a complete controlled automation subsystem.

## Memos Workflow

Purpose: improve development intelligence for the owner and agents.

Owns:
- Memory OS architecture, retrieval routing, memory snapshots.
- `llms.txt`, `strategy.md`, `AGENTS.md`, `AGENT_RULES.md`, `HANDSHAKE.md`.
- `task_capsules.jsonl`, `development_log.md`, proposal generation.
- Telemetry, method review, route optimization, self-analysis loops.
- Agent workflow rules and model step-size policy.

Default constraints:
- Keep agent docs concise and operational.
- Do not store raw secrets, `.env` values, or raw large logs.
- Prefer structural pointers over raw code chunks in memory.
- Separate durable rules from temporary handoff notes.

Typical tasks by score:
- 1 nano: add one handoff bullet; classify one task as product/memory_os.
- 2 micro: compact one log snippet into a capsule draft.
- 3 tiny: update one index pointer or one read-order line.
- 4 little: add one workflow rule or one task capsule validation.
- 5 pretty little: add one memory snapshot field or one telemetry summary.
- 6 light mid: add one Memory OS CLI/API read path with focused tests.
- 7 mid: wire method-review/proposal generation into one admin surface.
- 8 high mid: implement retrieval-router exact lookup plus test fixtures.
- 9 mid high: integrate telemetry -> insight -> proposal loop across modules.
- 10 big: build a usable Memory OS dashboard section with filters and actions.
- 11 large: design node/edge/event manifest lifecycle and validation states.
- 12 giant: repo-wide memory architecture audit and staged rebuild plan.

## Mixed Tasks

When a task touches both workflows:
- Split into `product` and `memory_os` subtasks in `HANDSHAKE.md`.
- Do not hide product risk inside memory_os work.
- Do not let memory_os refactors block a small product fix.
- If the user asks for "next" with no workflow, prefer the currently blocking handoff item.
