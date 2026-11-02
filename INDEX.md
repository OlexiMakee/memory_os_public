# Memory OS - Root Index

Welcome to the Memory OS project. This file serves as the primary map for AI agents and human developers navigating the repository. 

> **Mandatory Routing:** According to the global rules, ingestion paths must follow `INDEX.md` → `README.md` (if present) → `agent_context/CONTEXT.md`.

---

## 🧠 Agent Memory Tier
This tier maintains the dynamic operational context for agents working on this project.

* [HANDSHAKE.md](agent_context/HANDSHAKE.md) — Base alignment, rules, and behavioral boundaries for agents.
* [CONTEXT.md](agent_context/CONTEXT.md) — The most critical current state of the project.
* [development_log.md](agent_context/development_log.md) — The chronological changelog of implemented tasks.
* [GLOBAL_ROADMAP.md](agent_context/GLOBAL_ROADMAP.md) — The high-level strategic roadmap.
* [WORKFLOWS.md](agent_context/WORKFLOWS.md) — Common workflow definitions and pipelines.
* [SWARM_PROTOCOL.md](agent_context/SWARM_PROTOCOL.md) — Protocols for multi-agent execution and handoffs.
* [IMPORTANT_PROPOSAL.md](agent_context/IMPORTANT_PROPOSAL.md) — Strategic toolkit proposals, private.
* `agent_context/rfcs/` — Reserved for decisions on proposals that would change a fundamental subsystem rather than add a toolkit capability. Empty as of this writing: RFC-0002 (Git/blockchain-inspired memory architecture) was decided and its content fully absorbed into [roadmap.md](src/memory_os/docs/encyclopedia/roadmap.md)'s "Git Memory Chain (RFC-0002)" section, then deleted.

---

## 📚 Encyclopedia (Documentation)
Static documentation explaining the deep technical architecture of Memory OS.

* [Architecture](src/memory_os/docs/encyclopedia/architecture.md) — System boundaries and module connections.
* [Philosophy](src/memory_os/docs/encyclopedia/philosophy.md) — The underlying design concepts.
* [Database](src/memory_os/docs/encyclopedia/database.md) — SQLite schema and Knowledge Graph structure.
* [CLI Tools](src/memory_os/docs/encyclopedia/cli_tools.md) — How to interact via `python -m memory_os`.
* [Search](src/memory_os/docs/encyclopedia/search.md) — Hybrid and Temporal Knowledge Graph search logic.
* [Compaction](src/memory_os/docs/encyclopedia/compaction.md) — Merging and compressing memories via LLMs.
* [Lifecycle](src/memory_os/docs/encyclopedia/lifecycle.md) — Node status and freshness transitions.
* [Roadmap (Technical)](src/memory_os/docs/encyclopedia/roadmap.md) — Specific technical evolution phases.
* [LoRA Skill Adapters](src/memory_os/docs/encyclopedia/lora_training.md) — Local-first dataset/training-script prep for custom per-skill LoRA adapters (training runs on separate GPU hardware).
* [Agent Brain](src/memory_os/docs/encyclopedia/agent_brain.md) — Base-model action core + Orchestrator + Responder split: philosophy, architecture, and interfaces (tested today with no model; real adapter trained on separate GPU hardware).

---

## ⚙️ Core Architecture Directories
Key directories inside the implementation.

* [src/memory_os/cli.py](src/memory_os/cli.py) — The single CLI entrypoint.
* [src/memory_os/core/](src/memory_os/core/) — Core repository, storage, and SQLite `MemoryOS` wrapper.
* [src/memory_os/modules/](src/memory_os/modules/) — Sub-components (e.g. compactor, searcher).
* [src/memory_os/toolkit/](src/memory_os/toolkit/) — Standalone tool pipelines (sync, validation, extraction).
* [src/memory_os/llm/](src/memory_os/llm/) — LLM prompt definitions and integration.

---

*This file represents the ingestion entry point for any incoming AI agent.*
