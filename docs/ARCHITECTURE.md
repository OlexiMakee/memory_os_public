# Memory OS — Architecture

> Portable Agent Memory Kernel. Zero external dependencies. Drop this folder into any Python project.

## Overview

Memory OS is a self-contained, SQLite-backed memory layer for autonomous AI agents. It provides:
- **Graph memory** — nodes (rules, facts, configs, policies), edges, and lifecycle events
- **Telemetry** — LLM token/cost/latency tracking per prompt version
- **Compaction** — converts raw task capsules into structured knowledge nodes via LLM
- **Lifecycle** — draft → observed → verified → superseded transitions
- **Search** — graph traversal + codebase symbol search

## Directory Layout

```
memory_os/
  __init__.py          Public API surface
  core.py              MemoryOS — SQLite DB init, connection management
  interfaces.py        IMemoryOSConfig, IMemoryStorage, ILlmProviderService (DIP layer)
  config.py            MemoryOSConfig — reads memory_os.config.json
  storage.py           FileSystemMemoryStorage — JSONL/JSON I/O
  llm_service.py       DefaultLlmProviderService — lazy host adapter + env fallback
  validator.py         MemoryValidator — schema validation for nodes/edges/events
  compactor.py         MemoryCompactor — LLM-driven capsule compaction
  lifecycle.py         LifecycleManager — propose, transition, manifest, prune
  search.py            MemorySearcher — node + codebase symbol search
  context.py           ContextRegistry — snapshot builder
  optimizer.py         RouteOptimizer — recommend LLM provider based on telemetry
  versioner.py         PromptVersioner — template registry + SHA-256 integrity
  telemetry.py         TelemetryRecorder — SQLite telemetry writer
  toml_parser.py       parse_toml, load_toml_file — pure stdlib TOML parser
  prompt_formatter.py  wrap_in_xml, compress_dialog, etc.
  pyproject.toml       Standalone package descriptor
  docs/
    ARCHITECTURE.md    This file
```

## Dependency Inversion Pattern

All classes depend on `interfaces.py` abstractions, not concrete implementations:
- `IMemoryOSConfig` — swap config source (file, env, remote)
- `IMemoryStorage` — swap storage backend (filesystem, S3, DB)
- `ILlmProviderService` — swap LLM provider (Gemini, OpenAI, OpenRouter, local)

## LLM Resolution

`DefaultLlmProviderService` resolves in this order:
1. Tries `from app.services.llm_clients import LLMClientFactory` (host project adapter)
2. Falls back to direct stdlib HTTP using env vars:
   - `GEMINI_API_KEY` → Gemini API
   - `OPENROUTER_API_KEY` → OpenRouter
   - `OPENAI_API_KEY` → OpenAI

## Data Files (not part of the package, live in project root)

```
memory/
  nodes.jsonl          Knowledge graph nodes
  edges.jsonl          Knowledge graph edges
  events.jsonl         Lifecycle event log
  manifest.json        Checksum + count summary
agent_context/
  task_capsules.jsonl  Raw task capsules (input for compaction)
data/
  memory_os.db         SQLite: telemetry + memories tables
memory_os.config.json      Runtime config (memory_dir, capsules_file, etc.)
```

## Portability Instructions

To use in a new project:
1. Copy `memory_os/` folder
2. Copy `memory_os.config.json` (or write a new one)  
3. Copy `memory/` data folder (or start fresh — it will be created)
4. `from memory_os import MemoryOS, MemoryValidator, ...`
5. For LLM compaction: set `GEMINI_API_KEY` or `OPENROUTER_API_KEY` in `.env`

No Flask. No `app.*` imports. No governance DB. Pure Python stdlib.

## Philosophy: Local-First Computing

Memory OS follows a local-first computing philosophy. The system is designed to maximize useful local computation and minimize unnecessary LLM calls.

It treats the language model not as the whole system, but as one component in a broader local runtime: a dispatcher, interpreter, summarizer, and reasoning module used **only when language intelligence is actually needed**.

### Core Principles
1. **Local Preprocessing**: Search, indexing, filtering, classification, validation, caching, file operations, and structured computation must be handled by local tools, scripts, databases, and specialized models whenever possible.
2. **Resource Politeness**: Memory OS must use the available hardware rationally. CPU, GPU, RAM, and storage are treated as resources to be scheduled, balanced, and protected. The system adapts its workload to preserve enough resources for the user to continue working in parallel.
3. **LLM as Dispatcher, not Loader**: The goal is not to ask a large model to read raw files and solve everything. The goal is to build a local operating layer that prepares small, precise, high-value prompts and delegates only the truly necessary parts to an LLM.

### The Architectural Formula
* **LLM speaks little.**
* **Memory OS does a lot.**
* **Cloud is used only when it is worth it.**

*Data stays local. Computation stays local. LLM receives only the essence.*
