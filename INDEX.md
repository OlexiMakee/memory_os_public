# Memory OS - Root Index

Welcome to the Memory OS project. This file serves as the primary map for AI agents and human developers navigating the repository. 

> **Mandatory Routing:** According to the global rules, ingestion paths must follow `INDEX.md` → `README.md` (if present) → `agent_context/CONTEXT.md`.

---

## 🧠 Agent Memory Tier
This tier maintains the dynamic operational context for agents working on this project.

* [HANDSHAKE.md](file:///Users/oleksii/Documents/memory_os/agent_context/HANDSHAKE.md) — Base alignment, rules, and behavioral boundaries for agents.
* [CONTEXT.md](file:///Users/oleksii/Documents/memory_os/agent_context/CONTEXT.md) — The most critical current state of the project.
* [development_log.md](file:///Users/oleksii/Documents/memory_os/agent_context/development_log.md) — The chronological changelog of implemented tasks.
* [GLOBAL_ROADMAP.md](file:///Users/oleksii/Documents/memory_os/agent_context/GLOBAL_ROADMAP.md) — The high-level strategic roadmap.
* [WORKFLOWS.md](file:///Users/oleksii/Documents/memory_os/agent_context/WORKFLOWS.md) — Common workflow definitions and pipelines.
* [SWARM_PROTOCOL.md](file:///Users/oleksii/Documents/memory_os/agent_context/SWARM_PROTOCOL.md) — Protocols for multi-agent execution and handoffs.

---

## 📚 Encyclopedia (Documentation)
Static documentation explaining the deep technical architecture of Memory OS.

* [Architecture](file:///Users/oleksii/Documents/memory_os/src/memory_os/docs/encyclopedia/architecture.md) — System boundaries and module connections.
* [Philosophy](file:///Users/oleksii/Documents/memory_os/src/memory_os/docs/encyclopedia/philosophy.md) — The underlying design concepts.
* [Database](file:///Users/oleksii/Documents/memory_os/src/memory_os/docs/encyclopedia/database.md) — SQLite schema and Knowledge Graph structure.
* [CLI Tools](file:///Users/oleksii/Documents/memory_os/src/memory_os/docs/encyclopedia/cli_tools.md) — How to interact via `python -m memory_os`.
* [Search](file:///Users/oleksii/Documents/memory_os/src/memory_os/docs/encyclopedia/search.md) — Hybrid and Temporal Knowledge Graph search logic.
* [Compaction](file:///Users/oleksii/Documents/memory_os/src/memory_os/docs/encyclopedia/compaction.md) — Merging and compressing memories via LLMs.
* [Lifecycle](file:///Users/oleksii/Documents/memory_os/src/memory_os/docs/encyclopedia/lifecycle.md) — Node status and freshness transitions.
* [Roadmap (Technical)](file:///Users/oleksii/Documents/memory_os/src/memory_os/docs/encyclopedia/roadmap.md) — Specific technical evolution phases.

---

## ⚙️ Core Architecture Directories
Key directories inside the implementation.

* [src/memory_os/cli.py](file:///Users/oleksii/Documents/memory_os/src/memory_os/cli.py) — The single CLI entrypoint.
* [src/memory_os/core/](file:///Users/oleksii/Documents/memory_os/src/memory_os/core/) — Core repository, storage, and SQLite `MemoryOS` wrapper.
* [src/memory_os/modules/](file:///Users/oleksii/Documents/memory_os/src/memory_os/modules/) — Sub-components (e.g. compactor, searcher).
* [src/memory_os/toolkit/](file:///Users/oleksii/Documents/memory_os/src/memory_os/toolkit/) — Standalone tool pipelines (sync, validation, extraction).
* [src/memory_os/llm/](file:///Users/oleksii/Documents/memory_os/src/memory_os/llm/) — LLM prompt definitions and integration.

---

*This file represents the ingestion entry point for any incoming AI agent.*
