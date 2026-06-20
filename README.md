# Memory OS

**Local-first long-term memory for LLM agents.**

Memory OS gives your AI agent a persistent, indexed memory graph — so it stops forgetting everything between sessions.

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
| `sync` | Sync `memory/nodes.jsonl` -> SQLite FTS5 index |
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
    -> writes task_capsules.jsonl
    -> memory_os compact  (LLM extracts nodes)
    -> memory_os sync     (indexes to SQLite)
    -> memory_os search   (retrieves relevant context)
```

## Environment variables

Create a `.env` in your project root:

```bash
OPENAI_API_KEY=sk-...       # for compact/compress/prune (LLM operations)
OPENROUTER_API_KEY=...      # alternative provider
GEMINI_API_KEY=...          # alternative provider
```

LLM operations (`compact`, `compress`, `giant-scan`) require at least one key.
`init`, `validate`, `sync`, `search`, `review`, `approve`, `triage`, `query`, `backlinks` work offline.

## Agent integration

After `memory_os init`, add this to your `AGENTS.md` or `CLAUDE.md`:

```markdown
## Memory OS

Run `memory_os search "<topic>"` before starting any task.
For non-trivial feature work, run `memory_os spec init "<title>"` and keep spec/plan/tasks traceable.
After completing a task, append a capsule to `agent_context/task_capsules.jsonl`.
Run `memory_os sync` after any memory update.
Run `memory_os check-updates` periodically to print the canonical repository URL and contribution guidance.
For reusable Memory OS changes, open an issue/PR against `OlexiMakee/memory_os_public` or write a local proposal in `agent_proposals/`.
```

## Templates

Copy files from `templates/` into your project's `agent_context/`:

- `templates/CONTEXT.md` — project context template
- `templates/HANDSHAKE.md` — agent session handoff template
- `templates/WORKFLOWS.md` — 12-step task scale
- `templates/CONSTITUTION.md` — development principles for Memory OS projects
- `templates/specs/` — spec, plan, tasks, and checklist templates
- `templates/SWARM_PROTOCOL.md` — multi-agent orchestration protocol
- `templates/PROPOSALS.md` — contribution proposal protocol for reusable Memory OS changes
- `templates/scripts/` — LOCAL FIRST script scaffolds
- `templates/skills/` — skill/rules templates and examples

## Architecture

See `src/memory_os/docs/ARCHITECTURE.md` for the full system design.
