# Project Context

Project: Memory OS
State: Local-first Universal Context Graph and semantic memory prosthesis for LLM agents.
Runtime: macOS, Windows, or Linux with Last Python, `venv_auto/`, SQLite FTS5 (local).

## Single Source of Truth (SSOT)
- **Memory OS Root**: This directory (`memory_os`) is the definitive, authoritative source repository for the Memory OS framework.
- **Agent Enforcement**: All architectural changes, features, and fixes to Memory OS MUST be committed here and pushed to GitHub.
- **Independence**: This project is exclusively the Memory OS core engine. Do not assume or import contexts from downstream implementations (like News Research Automation, dashboards, or external APIs) unless explicitly integrating an `IDomainAdapter`.

## Domain Abstraction & Isolation Rules
- **Strict Separation of Core vs. Implementation**: This repository develops the Memory OS *engine*. It MUST NOT contain memory data, context, roadmaps, or agent instructions belonging to specific downstream implementations.
- **Feature Porting**: When committing features or bug fixes ported from other branches or downstream projects, you MUST commit **ONLY** the instrumentation, business logic, and framework code.
- **Zero Context Cross-Pollination**: Under NO circumstances should you touch, alter, or bring in `nodes.jsonl`, `edges.jsonl`, `CONTEXT.md`, roadmaps, or agent instructions from other projects into this SSOT root. The memory of the engine is distinct from the memory of its applications.

## Core Architecture
- **Concept**: A local neuro-semantic long-term memory layer (external hippocampus) that prevents LLM hallucinations through strict schema enforcement and relation patching.
- **Data Model**: `node → edge → metadata → evidence → lifecycle → index → retrieval`.
- **Storage**:
  - `nodes.jsonl`, `edges.jsonl`, `events.jsonl` (Immutable, ground-truth storage).
  - SQLite FTS5 (`graph_nodes`, `graph_edges`) for high-speed hierarchical and temporal retrieval.
- **CLI Ecosystem**: Memory OS provides a robust CLI via `python3 -m memory_os` for auditing, indexing, searching, and managing the graph.

## Common Commands
```bash
# General CLI help
python3 -m memory_os --help

# Sync JSONL changes to the SQLite FTS5 index
python3 -m memory_os sync

# Run interactive draft review
python3 -m memory_os triage

# Search and filter nodes
python3 -m memory_os query --status active

# Find inbound references and textual mentions
python3 -m memory_os backlinks <node-id>
```

## Multi-Agent Orchestration (Swarm Sync)
To prevent collisions and enable autonomous swarm operation for giant (L12) tasks, use:
```bash
python scripts/swarm_sync.py --agent="YOUR_NAME"
```

## Environment Variables
Never print .env values.

## Known Risks & Guidelines
- DB changes to the SQLite graph index should usually follow a `nodes.jsonl` / `edges.jsonl` update, followed by `memory_os sync`.
- Never store raw secrets or massive uncompressed logs in the graph. Use structural pointers instead.
- Maintain `Dependency Inversion (DIP)`: Keep the core generic and push domain-specific parsing (e.g., AST parsing) into Adapters.
