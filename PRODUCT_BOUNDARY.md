# Memory OS — Product Boundary & Open-Core Architecture

This document defines the strict boundary between the **Public Core (MIT)**, **Commercial Pro/Team**, and **Archived/Out-of-Scope** modules. Every public release MUST pass `memory_os release-check --target public`, including the automated Clean-Room gate.

---

## 1. Public Core (`MIT` — `pip install memory-os`)

Target: Single developer, local-first, zero mandatory external dependencies, 60-second setup.

**Positioning:** *Git-native Memory & Verification Control Plane for AI Coding Agents (Claude Code, Cursor, Codex).*

| Domain | CLI Commands (~15) | Core Modules |
| :--- | :--- | :--- |
| **Plain-File Memory** | `init`, `search`, `query`, `backlinks`, `memory log/show/revert` | `core/{storage,repository,retrieval,models,core}.py` |
| **Memory Hygiene** | `triage`, `approve`, `review`, `prune`, `transition`, `compact` | `toolkit/{lifecycle_cli,compaction_runner,memory_validator}.py` |
| **Verification Control Plane** | `spec`, `context`, `evidence`, `review-pack`, `security` (default profile), `doctor`, `release-check` | `core/{context_pack,evidence,security_scan,release_check}.py`, `toolkit/{spec_workflow,review_pack,doctor}.py` |
| **Codebase & Agent Interop** | `codebase`, `graph-map`, `mcp` (`stdio`), `mcp-install` | `adapters/mcp_adapter.py`, `memory_graph/`, `toolkit/graph_mapper.py` |
| **Licensing Hook (Core-safe)** | `license status/activate/verify` | `core/licensing.py` (provider-agnostic, stdlib-only) |

---

## 2. Commercial Tier (`Memory OS Pro` / `Team` — Private)

Target: Teams and power-users requiring automated CI enforcement, visual triage, and cross-machine/team sync.

1. **MVP 1 — CI/PR Verification Gate Pack (`B2`):**
   * GitHub Action (`action.yml`) + automated PR review comment (`evidence verify` + `review-pack` + `security scan --format sarif` uploaded to GitHub Security).
   * Merge-blocking enforcement when AI-generated PRs lack deterministic command evidence.
   * Multi-repo policy profiles & audit trail.
2. **Pro Solo & Team Expansion (Post-MVP):**
   * Local Web Graph & Visual Triage UI (`ui/{server,data_provider}.py`).
   * Encrypted cross-machine sync & Hosted Remote MCP (HTTP/SSE + RBAC + JSONL conflict resolver).
   * Optional Pro connectors (`linear_sync`, `notion_sync`, `obsidian_exporter`).

---

## 3. Out-of-Scope / Archived from Product v1 (`CUT`)

The following modules are excluded from public releases to prevent scope bloat, OS-specific fragility, and maintenance overhead:

* **Host OS / Desktop utilities:** `linux_inventory.py`, `toolkit/linux_provisioner.py`, `toolkit/xfce_manager.py`, `toolkit/startup_profile.py`, `toolkit/bootstrap_installer.py`, `ide_grant_private.py`.
* **Chat bots & custom orchestrators:** `adapters/telegram_*`, `adapters/discord_adapter.py`, `agent_brain/*`.
* **Terminal multiplexers & brittle quota scrapers:** `toolkit/multiplexer_manager.py`, `toolkit/agent_console_scanner.py`, `toolkit/console_parser.py`, `toolkit/quota_harvester.py`, `toolkit/agent_manager.py`.
* **ML / LoRA pipelines:** `lora/*`, `toolkit/quantizer.py`.
* **Non-core third-party adapters:** `duckdb`, `qdrant`, `phoenix`, `langfuse`, `mlflow`, `temporal`, `vllm`, `autogen`, `crewai`, `llamaindex`, `semantic-kernel`, `haystack`, `markitdown`, `gdrive_sync`.
* **Personal/legacy artifacts:** `user_persona/`.

---

## 4. Clean-Room & Packaging Rules

* Zero hardcoded local user paths (`/Users/...`, `/home/...`) in source, config, or docs.
* Zero references to private host projects or third-party client workflows.
* Mandatory `pyproject.toml` dependencies remain stdlib-only (`tomli` for Python < 3.11).
