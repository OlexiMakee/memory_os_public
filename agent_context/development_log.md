# Development Log: Memory OS

*Legacy News Research Automation logs have been archived/purged to maintain a clean context exclusively for Memory OS core development.*

## 2026-06-12: Context Purge & Core Focus
- **Refactor**: Completely purged all traces of the downstream "News Research Automation" product from the `agent_context/` directory.
- **Documentation**: Rewrote `CONTEXT.md`, `WORKFLOWS.md`, `HANDSHAKE.md`, and `GLOBAL_ROADMAP.md` to establish the Memory OS (Universal Context Graph) as the single source of truth for this repository.
- **Cleanup**: Deleted `active_memory.yaml` and wiped the old 47KB development log to prevent agent hallucination or context contamination.

## 2026-06-12: Autonomy Grant & Daemon Validation
- **Operations**: Verified that all global wildcard permissions are successfully granted in the user's config.json, and created local `AGENTS.md` for project-level command whitelisting.
- **Verification**: Re-executed the automated integration test suite (`test_auto.py`) successfully with `PYTHONPATH=src` after the session reload, confirming that execution runs without any manual prompts.
- **Status**: Checked and confirmed that the Memory OS background daemon is actively running and watching `agent_context/transcript.jsonl`.

## 2026-06-12: Desktop Notification Deactivation
- **Refactor**: Completely removed `osascript` AppleScript system calls from [AlertManager.send_alert](file:///Users/oleksii/Documents/memory_os/src/memory_os/core/alerts.py#L16). Alerts are now purely recorded to `data/alerts.log` to prevent desktop visual/audio spam during automated background runs.
- **Verification**: Executed [test_auto.py](file:///Users/oleksii/Documents/memory_os/test_auto.py) automatically. All test cases passed with no desktop popups.

## 2026-06-12: Background DB Auto-Optimization
- **Feature**: Integrated automated database optimization and vacuum scheduling in [MemoryDaemon](file:///Users/oleksii/Documents/memory_os/src/memory_os/core/daemon.py#L41) with a 24-hour interval.
- **Implementation**: The new `optimize_database` method handles WAL checkpoints, database vacuuming (`VACUUM`), and query planner analysis (`ANALYZE`) to optimize space and retrieve execution performance.
- **Verification**: Ran [test_auto.py](file:///Users/oleksii/Documents/memory_os/test_auto.py) successfully, confirming that the new scheduled task does not affect existing unit test expectations.

## 2026-06-12: Swarm Sync & File Locking
- **Feature**: Implemented [swarm_sync.py](file:///Users/oleksii/Documents/memory_os/scripts/swarm_sync.py) to manage the multi-agent task backlog and file-level leases transaction-safely.
- **Implementation**: Used `fcntl.flock` for exclusive file lock writes on `swarm_backlog.json` and `swarm_leases.json`. Designed folder-level prefix matching to detect edit conflicts when parallel workers target the same or parent/child directories.
- **Integration**: Refactored `swarm_invoke.py` to use `swarm_sync` for status changes, preventing file corruption.
- **Verification**: Added `test_swarm_sync()` to [test_auto.py](file:///Users/oleksii/Documents/memory_os/test_auto.py) verifying registration, conflict blocking, and status printing. All tests passed.

## 2026-06-12: Core CLI Stabilization & Happy Path Hardening
- **Fix**: Resolved interface mismatch in [TranscriptIngestor](file:///Users/oleksii/Documents/memory_os/src/memory_os/toolkit/transcript_ingestor.py) where `.generate()` was called on the LLM provider instead of `.call_llm()`. Added corresponding happy path integration tests using mock LLM stubs.
- **Feature**: Replaced subprocess execution in the `snapshot` CLI command with native Python execution of `ContextRegistry` in [cli.py](file:///Users/oleksii/Documents/memory_os/src/memory_os/cli.py).
- **Feature**: Added a new diagnostic tool `memory_os doctor` to audit critical directories, files, database health, API keys, and background process status.
- **Feature**: Expanded [MemoryValidator](file:///Users/oleksii/Documents/memory_os/src/memory_os/modules/validator.py) to whitelist AST-specific node types (`"file"`, `"class"`, `"function"`, `"module"`) and resolve relative evidence paths using a workspace file cache.
- **Daemon**: Implemented local state status reporting in [MemoryDaemon](file:///Users/oleksii/Documents/memory_os/src/memory_os/core/daemon.py) which logs uptime, watches configuration, and records last activity or errors to `data/daemon_status.json` without open sockets.

## 2026-06-12: Daemon HTTP API Server & Auto-Compaction Loop (Phases 8 & 9)
- **Fix**: Replaced the non-existent `compact_memory.py` subprocess runner in [MemoryCompactor](file:///Users/oleksii/Documents/memory_os/src/memory_os/modules/compactor.py) with native `ContextRegistry` instantiation to build memory snapshots safely.
- **Feature**: Implemented a localhost HTTP IPC server (`127.0.0.1:22467`) inside the background thread of [MemoryDaemon](file:///Users/oleksii/Documents/memory_os/src/memory_os/core/daemon.py). The server exposes GET `/status`, POST `/sync`, and POST `/stop` endpoints.
- **Feature**: Updated [cli.py](file:///Users/oleksii/Documents/memory_os/src/memory_os/cli.py) to enable `daemon stop`, `daemon status`, and a new `daemon sync` subcommand to communicate directly with the running daemon process over HTTP.
- **Feature**: Implemented background Time & Volume Triggered Auto-Compaction inside `MemoryDaemon` that scans for uncompacted capsules, checks the daily token budget using `BudgetManager`, and invokes the LLM compactor when $\ge 3$ uncompacted capsules are found.
- **Verification**: Extended automated integration test suite in [test_auto.py](file:///Users/oleksii/Documents/memory_os/test_auto.py) with `test_daemon_ipc_server` and `test_daemon_auto_compaction` verifying status, sync, stop, and budget skip rules. All integration tests passed successfully.

## 2026-06-13: Knowledge Base Tools Integration
- **Feature**: Ported new toolkit modules from the `knowledge_base` repository directly into `memory_os/src/memory_os/toolkit/`.
- **Implementation**: Integrated `link_inferrer.py` (LLM/text semantic edge discovery), `pipeline.py` (chained task execution), `notion_sync.py` (Notion DB memory extraction), `gdrive_sync.py` (Google Drive document extraction), and `graph_visualizer.py` (interactive 3D HTML export).
- **CLI**: Registered 5 new commands in `cli.py`: `notion-sync`, `gdrive-sync`, `export-3d`, `link-infer`, and `pipeline`.
- **Verification**: Validated that all commands are properly rendered in the CLI help menu and the syntax is error-free.

## 2026-06-13: 3D Graph Adaptive UI & Background Auditors
- **Feature**: Refactored `graph_visualizer.py` to use a responsive flexbox layout for HUD panels, preventing vertical overlap on small screens and fixing hardware metric panel text clipping.
- **Feature**: Added realtime `AuditorManager` and HTTP IPC monitoring for background daemon tasks (Ollama / ML mock auditors). Integrated system CPU/RAM usage tracking.
- **UI/UX**: Implemented copy-to-clipboard helper buttons in the UI for daemon start/stop CLI commands as a secure workaround for browser terminal execution limitations.
- **Fix**: Adjusted 3D force graph link rendering to use 1px faint lines for weak connections to prevent distant peripheral nodes from disappearing due to WebGL perspective clipping.

## 2026-06-13: UI Refactoring & Data Extractor Interface
- Refactored `graph_visualizer.py` extracting hardcoded templates to `src/memory_os/toolkit/ui_templates/`.
- Created `DataExtractor` and `DocumentIngestor` in `src/memory_os/toolkit/base_extractor.py`.
- Refactored `notion_sync.py` and `gdrive_sync.py` into dedicated extractors, removing direct file IO dependencies in favor of `DocumentIngestor`.
- Automated testing (`test_auto.py`) passed successfully.

## 2026-06-13: UI Refactoring Part 2 (Local Server & Adaptive Layout)
- **Feature**: Extracted Flask-free Python HTTP server into `src/memory_os/ui/server.py` serving static assets and dynamic API endpoints.
- **Feature**: Added root-level `ui_launcher.py` for direct quick access to the graph UI.
- **UI/UX**: Implemented `file-viewer-overlay` popup widget for reading node file contents (`.md`, `.py`, `.json`, `.js`) directly within the 3D graph view.
- **UI/UX**: Relocated Legend panel to the right column above the Hardware Metrics panel.
- **UI/UX**: Transformed the Graph Settings into an adaptive glassmorphism accordion widget anchored to the bottom of the left column. Added "Auto-Rotate" and fine-tuned settings options (Visuals & Physics).
- **Fix**: Added dynamic node sizing based on file size metadata. Added `Cache-Control: no-store` to the local HTTP server to prevent stale JavaScript serving.

## 2026-06-15: Agent Upstream Updates Enforcement
- **Feature**: Added `memory_os check-updates` CLI command to `cli.py` to output the upstream repository URL.
- **Feature**: Implemented local modification detection using `git status --porcelain` to warn users and agents if local core files have been modified.
- **Documentation**: Updated `README.md` and `templates/CONTEXT.md` to instruct agents to use the `check-updates` command and strictly enforce the behavioral contract of ONLY proposing changes to the memory_os core rather than modifying it directly downstream.

## 2026-06-15: Downstream Agent Proposals Integration (PR #1)
- **Fix**: Updated `ui_launcher.py` to gracefully handle address-in-use errors by terminating the previously orphaned server process or scanning for the next available port.
- **Fix**: Adjusted UI graph search filter to render a clear (✕) button for resetting applied graph search states.
- **Fix**: Hardened UI `isNodeLocalFile` check to correctly differentiate actual file nodes from generic concepts containing periods in their names, preventing 403 loading errors.
- **Fix**: Corrected the semantic dedup pass in `link_inferrer.py` to use a frozen pre-loop state `committed_pairs` for duplicate prevention rather than dynamically expanding it, allowing `--method text` to discover new implicit edges correctly.

## 2026-06-24: Context Packaging Engine Implementation
- **Feature**: Created [context_pack.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/context_pack.py) introducing the `ContextPackBuilder` class.
- **Feature**: Implemented contract parsing (JSON and Markdown formats), candidate gathering using `ContextRegistry`, secret guard and relevance scoring, memory node retrieval using `MemorySearcher`, deterministic stable ordering, and Markdown rendering.
- **Verification**: Verified using self-check Python command from repo root.

## 2026-06-24: Prompt Library and Idea Expansion (Stage 12)
- **Feature**: Created 10 prompt files under [prompts/](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/prompts/): `idea_expand.md`, `spec_builder.md`, `contract_builder.md`, `context_selector.md`, `implementation_planner.md`, `verification_planner.md`, `review_pack_builder.md`, `eval_designer.md`, `security_reviewer.md`, `memory_update.md`.
- **Feature**: Implemented [prompt_registry.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/prompt_registry.py) with `PromptRegistry` class.
- **Implementation**: The registry reads markdown templates relative to the package location, parses YAML frontmatter using a simple regex-based parser, extracts the template body, and provides methods to list, show, verify, and render prompts.
- **Dry-run**: Added `idea_expand_dry_run` for dry-running the idea expansion workflow without calling any LLM API.
- **Verification**: Verified using self-check Python command and confirmed all automated tests continue to pass.

## 2026-06-24: MLflow Exporter Implementation (Stage 14)
- **Feature**: Created [mlflow_exporter.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/adapters/mlflow_exporter.py) introducing the `MLflowExporter` class and `is_available` helper.
- **Implementation**: The exporter reads evidence bundles from `agent_context/evidence/*/bundle.json` and models them as MLflow runs with task IDs as run names, risk class as a tag, and total/failed commands as metrics. It lazily imports mlflow within try/except blocks to avoid hard dependencies.
- **Verification**: Verified using the self-check Python snippet and ran the complete automated integration test suite successfully.

## 2026-06-24: Security and Correctness Audit of Tier 3 Adapters
- **Audit**: Conducted a thorough, read-only security and correctness audit of four Tier 3 adapters: `qdrant_adapter.py`, `phoenix_exporter.py`, `langfuse_exporter.py`, and `mlflow_exporter.py`.
- **Findings**: Identified 4 exception-swallowing discipline violations where database, filesystem, or package import operations could raise unhandled exceptions outside protected blocks and crash the caller.
- **Reporting**: Created the audit report at [audit_adapters_tier3.md](file:///Users/oleksii/Documents/sandbox/memory_os/agent_context/audits/audit_adapters_tier3.md) detailed with failure scenarios and recommended fixes.

## 2026-06-24: Security and Correctness Audit of Prompts and Prompt Registry
- **Audit**: Conducted a thorough, read-only security and correctness audit of `prompt_registry.py` and all prompt files under `src/memory_os/toolkit/prompts/`.
- **Findings**: Verified that the template replacement mechanism is secure from template injection, that path traversal is prevented as the prompt ID is never used to build file paths directly, that `verify()` handles malformed frontmatter gracefully without crashing, and that all prompt files are aligned with security constraints. No issues were found.
- **Reporting**: Created the audit report at [audit_prompts.md](file:///Users/oleksii/Documents/sandbox/memory_os/agent_context/audits/audit_prompts.md).

## 2026-06-24: Security and Correctness Audit of Tier 2 Adapters
- **Audit**: Conducted a thorough, read-only security and correctness audit of five Tier 2 adapters: `ollama_adapter.py`, `markitdown_adapter.py`, `otel_exporter.py`, `duckdb_adapter.py`, and `litellm_adapter.py`.
- **Findings**: Identified 4 issues including exception leakage in `litellm_adapter.py`, `otel_exporter.py`, and `markitdown_adapter.py`, and a path traversal read vulnerability in `markitdown_adapter.py`.
- **Reporting**: Created the audit report at [audit_adapters_tier2.md](file:///Users/oleksii/Documents/sandbox/memory_os/agent_context/audits/audit_adapters_tier2.md) detailed with failure scenarios and recommended fixes.

## 2026-06-24: Bounded Telemetry and Disk Guard Audit Fixes
- **Fix**: Changed `created_at` column DEFAULT from `datetime('now', 'localtime')` to UTC `datetime('now')` in both `memory_os_telemetry` and `memory_os_performance` table schemas in [core.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/core.py) to prevent timezone offset discrepancies during retention pruning.
- **Fix**: Added missing database index `idx_performance_created` on the `created_at` column of the `memory_os_performance` table in [core.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/core.py) to avoid full-table scans.
- **Fix**: Updated `TelemetryPolicy.prune()` in [telemetry_policy.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/telemetry_policy.py) to run `VACUUM` when rows were deleted and the database file size still exceeds the maximum configured size limit.
- **Fix**: Wrapped the file stat call inside `DiskGuard._jsonl_total_mb` in [disk_guard.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/disk_guard.py) to handle `FileNotFoundError` when files are deleted concurrently during compaction.
- **Fix**: Wrapped `shutil.disk_usage()` inside `DiskGuard._free_disk_mb` in [disk_guard.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/disk_guard.py) with try/except to prevent uncaught crashes if the configured `root_dir` does not exist.
- **Fix**: Added a minimum elapsed-time guard in `DiskGuard.snapshot()` in [disk_guard.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/disk_guard.py) to skip growth rate recomputation and keep the previous value if less than 60 seconds have elapsed.

## 2026-06-24: Security Bug Fixes for Tier 3 Adapters
- **Fix**: Moved `qdrant_client` import inside the main try-except block of `QdrantAdapter.health_check()` to catch non-ImportError failures.
- **Fix**: Wrapped initialization of `MemoryOS` and SQLite connections inside the try-except blocks of `PhoenixExporter.export()` and `LangfuseExporter.export()`.
- **Fix**: Wrapped the entire `MLflowExporter.export()` method body in a single top-level try-except block to gracefully handle filesystem and path checking errors.
- **Verification**: Verified using import self-check command and executed the automated test suite successfully.

## 2026-06-24: Adversarial Security and Correctness Audit of transcript_ingestor.py and giant_scan.py
- **Audit**: Conducted a thorough, read-only security and correctness audit of `transcript_ingestor.py` and `giant_scan.py`.
- **Findings**: Identified 5 issues including unbounded memory usage in log parsing and repository scanning, unhandled type conversion crash in transcript log parsing, scan root path suffix bypass, and symlink disclosure vulnerabilities.
- **Reporting**: Written full findings to `agent_context/audits/audit2_transcript_giant_scan.md`.

## 2026-06-24: Security and Correctness Audit of Storage, Repository, and Patch
- **Audit**: Conducted a thorough, read-only security and correctness audit of `storage.py`, `repository.py`, and `patch.py`.
- **Findings**: Identified 9 issues including uninitialized patches cache blocking patch lifecycle, unbounded SQLite connection overhead in index sync, silent patch application failures for soft delete and deprecate operations, lack of concurrency/locking control, unbounded JSONL growth, and fragile deserialization logic.
- **Reporting**: Created the audit report at [audit2_storage_patch.md](file:///Users/oleksii/Documents/sandbox/memory_os/agent_context/audits/audit2_storage_patch.md) detailing severity, concrete exploit/failure scenarios, and suggested fixes.



## 2026-06-24: Security and Correctness Audit of External Sync Integrations
- **Audit**: Conducted a thorough, read-only security and correctness audit of three external sync integrations: `notion_sync.py`, `gdrive_sync.py`, and `linear_sync.py`.
- **Findings**: Identified 5 issues including a NameError crash in Notion sync, missing HTTP client timeouts in all three modules, unbounded download file size in GDrive sync (OOM risk), missing pagination in Linear sync (duplicate issue creation), and a credentials leak in the pipeline command display wrapper (for GDrive tokens).
- **Reporting**: Created the audit report at [audit2_external_sync.md](file:///Users/oleksii/Documents/sandbox/memory_os/agent_context/audits/audit2_external_sync.md).

## 2026-06-24: Security and Correctness Audit of daemon.py
- **Audit**: Conducted an adversarial security and correctness audit of `src/memory_os/core/daemon.py`.
- **Findings**: Identified 7 issues including wildcard CORS/no-auth on localhost IPC endpoints, dynamic space switching path traversal, single-threaded blocking DoS, log file truncation ingestion bypass, parallel daemon cursor clobbering/race condition, HTTP exception trace leaks, and excessive disk write performance concerns.
- **Reporting**: Written the findings to the audit report at [audit2_daemon_ipc.md](file:///Users/oleksii/Documents/sandbox/memory_os/agent_context/audits/audit2_daemon_ipc.md).

## 2026-06-24: Security and Correctness Audit of UI Server
- **Audit**: Conducted a thorough, read-only security and correctness audit of `src/memory_os/ui/server.py` and `src/memory_os/ui/data_provider.py`.
- **Findings**: Identified 7 issues including path traversal/arbitrary file read inside the project root via `/api/read_file`, path traversal/sibling directory bypass in `_resolve_file_path`, missing CORS access restrictions / Origin validation (wildcard CORS), unvalidated space path traversal in `/api/switch_space`, unbounded POST body reads (DoS), unbounded file reads (DoS), and unvalidated CLI argument execution in `/api/link-infer`.
- **Reporting**: Created the audit report at [audit2_ui_server.md](file:///Users/oleksii/Documents/sandbox/memory_os/agent_context/audits/audit2_ui_server.md).

## 2026-06-24: Security and Correctness Audit of Swarm Orchestration Scripts
- **Audit**: Conducted a thorough, read-only security and correctness audit of `scripts/swarm_invoke.py` and `scripts/swarm_sync.py`.
- **Findings**: Identified 4 issues including false-positive rate-limit match denial of service, lock conflict bypass for tasks in `pending_limit` status, silent database wipeout on JSON parse failures, and lack of subprocess execution timeouts.
- **Reporting**: Written the findings to the audit report at [audit2_swarm_scripts.md](file:///Users/oleksii/Documents/sandbox/memory_os/agent_context/audits/audit2_swarm_scripts.md).

## 2026-06-24: External Sync & Pipeline Security Remediation Fixes
- **Fix (FIX 1)**: Added `fetch_page_content` wrapper in [notion_sync.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/notion_sync.py#L222-L224) delegating to `get_page_content_markdown_recursive` to resolve `NameError` crash.
- **Fix (FIX 2)**: Added `timeout=30` to every `urllib.request.urlopen` call in [notion_sync.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/notion_sync.py), [gdrive_sync.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/gdrive_sync.py), and [linear_sync.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/linear_sync.py).
- **Fix (FIX 3)**: Checked `Content-Length` header in `download_gdrive_file_content` in [gdrive_sync.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/gdrive_sync.py#L55-L62); skips download and returns a placeholder if file size exceeds 10MB.
- **Fix (FIX 4)**: Implemented cursor-based pagination loop in `get_linear_issues` in [linear_sync.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/linear_sync.py#L28-L61) using GraphQL's `pageInfo { hasNextPage endCursor }` and `after` variable to prevent duplicate issue creation.
- **Fix (FIX 5)**: Masked `--token <value>` alongside `--api-key` in `_redact_for_display` in [pipeline.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/pipeline.py#L34-L38) to prevent OAuth credentials leakage.
- **Verification**: Verified successfully with module import self-check command and running the full automated integration test suite (`test_auto.py`).

## 2026-06-24: Knowledge Compactor Security Remediation
- **Fix (FIX 1)**: In `compact_capsules()` inside [compactor.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/modules/compactor.py#L384-L417), added a check requiring that any proposed edge of type `overrides` or `refutes` has its source node proposed and accepted in the same batch. Rejects/skips non-compliant edges and logs them as `memory.edge.rejected` to `events.jsonl`.
- **Fix (FIX 2)**: In `compress_graph()` inside [compactor.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/modules/compactor.py#L611-L687), restricted compression edges to type `overrides` only (rejecting others like `refutes`), verified the type is in `VALID_EDGE_TYPES`, and verified that the source node is one of the newly accepted merged nodes from the current EvolutionGate run. Logs rejected edges to `events.jsonl`.
- **Fix (FIX 3)**: Added a private `_record_planned_deprecations` helper in [compactor.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/modules/compactor.py#L188-L237) to calculate and write `memory.node.deprecation_planned` events to `events.jsonl` right before calling `transition()` + `prune()`. Verified that `dry_run` mode in `compress_graph()` genuinely skips calling transition and pruning functions.
- **Verification**: Built an automated replication script (`test_repro.py`) confirming rejected proposed nodes in a batch with a refutes edge are successfully filtered and logged, and successfully ran the automated test suite `test_auto.py`.



## 2026-06-25: Memory Extractor Script
- **Feature**: Added `scripts/memory_extract.py` as a legacy-compatible dry-run extractor. It defaults to a read-only summary, safely interacts with the `memory_os` workspace graph, and strictly confines writes inside the project root using `ArtifactWriteBudget`.
- **Feature**: Added support for formatting (`text`, `json`, `markdown`), custom graph sources, and skipping private/export-ignored files via policy integration.
- **Fix**: Added `.gitignore` exclusion for local `memory_extract` artifact directories.
- **Verification**: Executed isolated tests for `memory_extract` script and full integration suite (`test_auto.py`) successfully. Found 177 duplicate node ids during workspace graph validation.
- **Feature**: Created `scripts/dedup_graph.py` to deduplicate nodes and edges based on ID, merging lists (e.g. evidence, tags) and preserving the latest scalar fields.
- **Operations**: Executed deduplication on the local workspace graph, cleaning up 177 duplicate nodes and 188 duplicate edges. Verified with `test_auto.py`.

2026-06-25: Federated UI & Tier 4 Bridges
- Feature: Added `_find_federated_spaces` in `src/memory_os/ui/server.py` to allow discovering other Memory OS instances in sibling directories.
- Feature: Updated `/api/switch_space` to securely load federated configs in read-only mode, blocking mutating endpoints.
- Feature: Added `src/memory_os/adapters/bridges/` with lazy-loading integrations for `autogen_bridge.py`, `crewai_bridge.py`, `llamaindex_bridge.py`, `semantic_kernel_bridge.py`, `haystack_bridge.py`.
- Quality: Created `test_bridges_and_ui.py`. Verified all local system tests passed via `test_auto.py`.


## 2026-06-25: Documentation, CI/CD & Tier 4 Bridges Fixes
- **Docs**: Created  and  for onboarding.
- **Fix**: Updated  to  across all Tier 4 bridge adapters.
- **CI/CD**: Added  dependencies to .
- **CI/CD**: Created  for automated testing across Python 3.9-3.12.
- **Verification**: Executed  and  locally.


## 2026-06-25: Documentation, CI/CD & Tier 4 Bridges Fixes
- **Docs**: Created `QUICKSTART.md` and `examples/simple_agent.py` for onboarding.
- **Fix**: Updated `MemorySearcher.search` to `search_memory` across all Tier 4 bridge adapters.
- **CI/CD**: Added `adapters-*` dependencies to `pyproject.toml`.
- **CI/CD**: Created `.github/workflows/test.yml` for automated testing across Python 3.9-3.12.
- **Verification**: Executed `test_auto.py` and `test_bridges_and_ui.py` locally.

## 2026-06-25: Advanced AI Memory Architectures
- **Feature**: Implemented Temporal Knowledge Graphs by adding `valid_from` and `valid_until` fields to `MemoryNode` in `src/memory_os/core/models.py`.
- **Feature**: Modified `RelationPatchStore` (`src/memory_os/core/patch.py`) and `LifecycleManager` (`src/memory_os/modules/lifecycle.py`) to automatically record validity timestamps when nodes transition between verified and stale/superseded statuses.
- **Feature**: Replaced substring matching in `MemorySearcher.search_memory` (`src/memory_os/modules/search.py`) with a pure-Python Fuzzy Semantic Search (tokenized overlap scoring BM25-lite) to improve resilience and relevance scoring.
- **Verification**: Executed the full test suite (`test_auto.py`) successfully with no regressions.

## 2026-06-25: Layered Retrieval & Memory Tiering Abstraction
- **Feature (A1)**: Implemented Layered Retrieval (Phase 5) by adding `search_graph_nodes` to `MemoryOS` (`src/memory_os/core/core.py`). This leverages SQLite FTS5 `BM25` ranking for database-level graph search scaling.
- **Feature (A1)**: Refactored `MemorySearcher.search_memory()` (`src/memory_os/modules/search.py`) to transparently route all searches through the SQLite indexer when available, falling back to Python fuzzy search if unindexed.
- **Feature (B1)**: Implemented explicit Memory Tiering (RAM/Disk Abstraction) by adding `format_memory_tier_status` to `src/memory_os/core/prompt_formatter.py`. This injects XML-formatted status alerts to the agent when its context approaches capacity, explicitly instructing it to page out to Disk.
- **Verification**: Verified using automated tests (`test_auto.py`) and manual FTS5 querying via Python CLI.

## 2026-06-25: Algorithmic Forgetting & Retrieval Caching
- **Feature (B1)**: Implemented FTS5 Query Caching Layer (Phase 6). Added `get_version_hash()` to `MemoryRepository` that returns the `mtime` of the `nodes.jsonl` database. Implemented a bounded cache in `MemorySearcher.search_memory()` that utilizes this hash to guarantee 100% freshness, dropping repeat search times from ~130ms to ~0.0001ms.
- **Feature (A1)**: Implemented Algorithmic Memory Decay (Ebbinghaus approximation).
    - Updated `MemoryNode` and SQLite schema `graph_nodes` to include `access_count` and `last_accessed` tracking.
    - `MemorySearcher` now silently calls `log_node_access` after finding hits to increment their survival score.
    - Added `LifecycleManager.decay_nodes(days_stale=30)` to automatically generate patches transitioning unaccessed old nodes to `archived`.
    - Heavily penalized `archived` nodes in search (downranked 90%), preventing context bloat while keeping them accessible if explicitly matched.
- **Verification**: Executed 172 unit tests with 100% pass rate. Verified cache latencies manually.
