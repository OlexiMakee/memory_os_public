# Memory OS

**Local-first development toolkit and long-term memory for LLM agents.**

Memory OS gives your AI agent a persistent, indexed memory graph plus repeatable workflows for spec-driven planning, verification, and agent handoff quality.

> *The LLM shouldn't remember everything. It should know how to ask Memory OS.*

## Install

```bash
pip install git+https://github.com/OlexiMakee/memory_os_public.git
```

Or clone and install locally:

```bash
git clone https://github.com/OlexiMakee/memory_os_public.git
cd memory_os_public
pip install -e .
```

## Quickstart (5 minutes)

```bash
# 1. Initialize Memory OS in your project root
cd your-project/
memory_os init

# 2. Verify everything is wired up
memory_os validate

# 3. Sync memory to the search index
memory_os sync

# 4. Search memory
memory_os search "authentication"

# 5. Review and approve draft memory nodes
memory_os triage
```

## Core Commands

| Command | What it does |
|---|---|
| `init` | Create memory files and config in current directory |
| `validate` | Check that memory files and capsules are valid |
| `sync` | Sync `memory/nodes.jsonl` → SQLite FTS5 index |
| `search <query>` | Keyword search across memory nodes |
| `snapshot` | Build a compact memory snapshot for agent context |
| `spec init <title>` | Create spec/plan/tasks/checklist files for a feature |
| `spec analyze [id]` | Validate spec quality gates and traceability |
| `spec constitution` | Install project development principles |
| `compact` | Extract new memory nodes from task capsules via LLM |
| `compress` | Semantically merge duplicate memory nodes |
| `prune` | Archive stale and superseded nodes |
| `transition` | Promote draft nodes through lifecycle states |
| `review` | List draft nodes pending approval |
| `approve <id>` | Approve a draft node |
| `triage` | Interactive review of draft nodes |
| `query` | Filter nodes by type, status, trust, tag, date |
| `backlinks <id>` | Show all nodes that reference a given node |
| `audit` | Audit control-plane state |

## Engineering Control Plane

The engineering control plane turns a vague request into a verified result: idea -> spec -> contract -> context -> implementation -> evidence -> review. These commands have read-only or `--dry-run` paths that work fully offline with no LLM call required, so agents can inspect, route, and verify work before invoking a model.

| Command | What it does |
|---|---|
| `idea expand --text "..."` | Turn a rough idea into a structured discovery brief prompt |
| `contract build <spec-id>` | Derive risk class, rollback plan, and acceptance criteria from an existing spec |
| `context build --task "..."` | Build a targeted, reproducible context pack instead of dumping the repo into the model |
| `evidence init/add-command/verify --task <id>` | Record commands run and exit codes, then block "done" until recorded checks passed |
| `review-pack --task <id>` | Assemble contract, context pack, and evidence into one reviewer-facing document |
| `change-size` | Warn when a change touches too many files or mixes source with generated artifacts |
| `eval list/run/compare` | Run local-deterministic and optional LLM-judge eval suites for nondeterministic behavior |
| `security scan --profile <profile>` | Scan local memory, private docs, context artifacts, or docs for secrets and injection markers |
| `resources snapshot/checkpoint/compact` / `telemetry audit/prune` | Check and bound disk, SQLite WAL, JSONL, and telemetry growth |
| `release-check --target private/public` | Run deterministic local gates before publishing |
| `route --task "..."` / `budget status` | Show provider/model routing and current token budget status without a network call |
| `prompt list/show/render` | Inspect versioned, hashed prompt templates without an LLM call |
| `adapters audit` | Check which optional adapters are installed; none are required by default |
| `run start/status/complete` | Keep lightweight native run and checkpoint records for multi-step workflows |

## How it works

Memory lives in `memory/nodes.jsonl` and `memory/edges.jsonl` — plain text files you can read and edit.

Agents write **task capsules** to `agent_context/task_capsules.jsonl` when they complete work. Running `memory_os compact` extracts structured memory nodes from those capsules via LLM. Running `memory_os sync` indexes them into SQLite FTS5 for fast search.

For non-trivial development work, agents can run `memory_os spec init "<title>"` to create a plain-file feature workspace:

```
specs/001-example/
    spec.md
    plan.md
    tasks.md
    checklist.md
```

`memory_os spec analyze` checks for unresolved clarification markers, numbered requirements, acceptance scenarios, constitution checks, and task traceability.

```
agent completes task
    → writes task_capsules.jsonl
    → memory_os compact  (LLM extracts nodes)
    → memory_os sync     (indexes to SQLite)
    → memory_os search   (retrieves relevant context)
```

## Environment variables

The base package has no mandatory third-party runtime dependencies. Provider SDKs
and heavier tooling are installed through extras, for example:

```bash
pip install "memory_os[providers-ollama]"
pip install "memory_os[providers-openai]"
pip install "memory_os[resource-psutil]"
pip install "memory_os[all]"
```

Create a `.env` in your project root:

```bash
OPENAI_API_KEY=sk-...       # for compact/compress/prune (LLM operations)
OPENROUTER_API_KEY=...      # alternative provider
GEMINI_API_KEY=...          # alternative provider
```

LLM operations (`compact`, `compress`, `giant-scan`) require at least one key.
`init`, `validate`, `sync`, `search`, `review`, `approve`, `triage`, `query`, `backlinks` work offline.

`python3 test_auto.py` runs against an isolated temporary Memory OS workspace by default. Use `python3 test_auto.py --live-smoke` only when intentionally testing the current checkout's live runtime state.

## Agent integration

After `memory_os init`, add this to your `AGENTS.md` or `CLAUDE.md`:

```markdown
## Memory OS

Run `memory_os search "<topic>"` before starting any task.
For non-trivial feature work, run `memory_os spec init "<title>"` and keep spec/plan/tasks traceable.
After completing a task, append a capsule to `agent_context/task_capsules.jsonl`.
Run `memory_os sync` after any memory update.
Run `memory_os check-updates` periodically to find the public repository URL.
For public-facing work, use the public repository's normal issue/PR flow. Keep private planning files such as `DEV_STRATEGY.md` and `agent_context/IMPORTANT_PROPOSAL.md` on private remotes only.
```

## Templates

Copy files from `templates/` into your project's `agent_context/`:

- `templates/CONTEXT.md` — project context template
- `templates/HANDSHAKE.md` — agent session handoff template  
- `templates/WORKFLOWS.md` — 12-step task scale
- `templates/CONSTITUTION.md` — development principles for Memory OS projects
- `templates/specs/` — spec, plan, tasks, and checklist templates
- `templates/SWARM_PROTOCOL.md` — multi-agent orchestration protocol
- `templates/PROPOSALS.md` — how agents propose upstream changes (bugs, features, schema)
- `templates/AGENT_RULES.md` — handshake verification and step-tier rules
- `templates/scripts/` — LOCAL FIRST script scaffolds
- `templates/skills/` — skill/rules templates and examples

## Architecture

See `src/memory_os/docs/ARCHITECTURE.md` for the full system design.
