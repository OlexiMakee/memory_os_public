# Global Roadmap: Governed Autonomous Intelligence Workspace

Status: reformed on 2026-06-02 based on the autonomous_intelligence_hub_strategy_v3.md GTM directive and deep-research-report.md memory model.

---

## Strategic Phases

### Phase 0: Strategy & Category Alignment
- [x] Rename category to **Governed Autonomous Intelligence Workspace** across core documentation and UI titles.
- [x] Define acceptable use boundaries, misuse prohibition rules, and source policy tiers (A, B, C, D, E, X) inside [CONTEXT.md](file:///Users/oleksii/Documents/News%20Research%20Automation/agent_context/CONTEXT.md).
- [x] Implement initial progressive entitlement scaffolding (`ready_workspace`, `dense_workspace`, `linked_intelligence`, `operator_runtime`, `autonomous_watchers`) in [CONTEXT.md](file:///Users/oleksii/Documents/News%20Research%20Automation/agent_context/CONTEXT.md).
- [x] Remove duplicate workspace tabs in top bar; consolidate navigation exclusively within the left sidebar.
- [x] Configure responsive paddings and transitions on `.modal-overlay` for dynamic centering based on sidebar and chat drawer visibility.
- [x] Set default left sidebar state to collapsed on startup and add click-outside closure listener in [app.js](file:///Users/oleksii/Documents/News%20Research%20Automation/static/js/app.js).
- [x] Add inline warning-styled "Assistant" button to modal actions panel to stream video context directly into the AI chat.
- [x] Automatically append active dashboard filter values (dates, channels) and system time to AI chat context.

### Phase 1: Editorial MVP
- [x] **Source Registry UI**: Implement a dashboard panel to add, edit, and inspect source registry state.
- [x] **Ingestion Pipeline**: Build ingestion hooks for YouTube API, RSS feeds, and manual file uploads, complete with frontend UI run triggers.
- [x] **Deep Topic Study Primitive**: Add customer-scoped topic analytics with probabilities, correlations, anomalies, evidence, and caveats.
- [x] **Generic Phrase Performance Primitive**: Rank 1/2/3/4-gram phrases by views, likes, comments, growth metrics, engagement, medians, totals, lift, and evidence samples.
- [x] **Phrase Performance Chart API Integration**: Derive dashboard word/hashtag/title/thumbnail phrase metrics from the generic scorer instead of the legacy `video_phrases` table path.
- [x] **Data Access Experiment Loop**: Add file-backed method experiment logs and ranking for data-reading approaches.
- [x] **Ingestion API Foundation**: Add admin/entitlement-gated `GET /api/source-connectors` and `POST /api/sources/ingest` for dry-run-first YouTube/RSS/manual connector execution and optional governance-registry persistence.
- [x] **Transcript Extraction**: Permitted automated transcription workflows (with M4A audio extraction and download).
- [x] **Daily Brief Template**: Design structured template widgets rendering yesterday's key stories and metrics.
- [x] **Source-Backed Briefs**: Connect LLM brief generation to reference source citations.
- [x] **Compact Grid v1**: Upgrade dashboard workspace grid to support resizable, collapsible cards.
- [x] **Copy-as-Brief Export**: Add single-click button copying the generated markdown brief with footnotes/citations.
- [x] **Source Records Surfacing**: Add read-only source record previews in Operator Runtime after persisted ingestion.
- [x] **Basic Roles**: Implement reader, analyst, and administrator UI visibility rules based on active user role.
- [x] **Proposal Inbox Workflow Classification**: Keep one file-backed proposal inbox, but add backward-compatible `workflow`, `origin`, `authority`, `role_title`, and `created_by` metadata so product and Memory OS proposals can be filtered without splitting persistence yet.

### Phase 2: Dense Workspace & Entity Tracking
- [x] **Saved Layouts**: Save grid widget positions and dimensions to database widgets table.
- [x] **Micro-Widgets**: Build minified stat cards, compact timeline tracks, and status indicator lights.
- [x] **Synchronized Filters**: Propagate channel checkboxes, search queries, and date ranges across all widgets.
- [x] **Entity Extraction**: Deploy models to extract political actors, organizations, and locations from descriptions.
- [x] **Alias Dictionary**: Group name variations (e.g., "UATV", "UA TV") under single canonical entities.
- [x] **Cross-Source Timeline**: Render a unified timeline showing when specific entities are mentioned across channels.
- [x] **Cost & Quota Dashboard**: Expose real-time API call counts and model token budgets.
  - [x] **Scraper Workflows & Cost/Delay Estimation**: Integrate five workflows (super economical to ultra fast), budget constraints, and cost previews.


### Phase 3: Evidence & OSINT Mode
- [x] **Artifact Store**: Cache raw source data (HTML pages, video thumbnails, descriptions) with immutability hashes.
- [x] **Timestamp & Hash Verification**: Cryptographically timestamp exported summaries.
- [x] **Evidence Bundle Export**: Zip raw artifacts, screenshots, and logs into a single downloadable proof zip.
- [x] **Audit Logging**: Write critical user actions (source modifications, export triggers, credentials modifications, and scraper proposal approvals) to SQLite `audit_events` in `governance.db`.
- [x] **Retention Locks**: Implement auto-purge rules for high-risk Tier E scraper caches.
- [x] **Tri-View (Graph, Timeline, Table)**: Toggle workspace views between raw tables, chronologies, and entity connection maps.

### Phase 4: Controlled Automation
- [ ] **Scheduled Watchers**: Configure background cron workers to scan source feeds every N hours.
- [ ] **Budget & Token Caps**: Set hard limits on watcher API spends.
- [ ] **Human Review Queue**: Hold autonomous reports in draft status until approved by an Editor or Analyst.
- [ ] **Anomaly Alerts**: Push Slack, Telegram, or email notifications for Z-score alerts meeting threshold.

### Phase 5: Enterprise Hardening
- [ ] **Bring Your Own Key (BYOK)**: Let teams supply custom LLM provider credentials.
- [ ] **Multi-Team RBAC**: Support granular workspace isolation for distinct team accounts.
- [ ] **SAML/SSO integration**: Configure corporate identity provider logins.
- [ ] **Secure Air-Gapped Profiles**: Lock down all telemetry, cloud backups, and third-party API emitters for maximum security.

---

## Code Refactoring & Memory OS

### SOLID Cleanups
- [x] **SRP Refactoring**: Split the `AgentService` class into separate services (`SystemPromptBuilder`, `LLMOrchestrator`, `QuotaRotationEngine`, `ChatLogger`).
- [x] **OCP Extension**: Define a `BaseLLMClient` interface and derive specific client subclasses (`GeminiClient`, `OpenRouterClient`, `OllamaClient`, `OpenAIClient`) to resolve client instances via factory methods.
- [x] **ISP Separation**: Segregate the wide database client storage interface (`BaseStorage`) into small repository contracts (`IChannelRepository`, `IVideoRepository`, `ISyncCoordinator`).

### Memory OS Operations
- [x] **ADR-004: Memory OS Kernel and Task Quantization**: Write architectural contract defining context budgeting, routing escalation, and YAML workflow specs.
- [x] **Memory OS MVP v0.1 Core Package**:
  - [x] Initialize `memory/` directory with `schema.json` and JSONL templates for nodes, edges, events, and task capsules.
  - [x] Implement `scripts/memory/validate_memory.py` to validate metadata schema compliance and evidence pointers.
  - [x] Implement `scripts/memory/quantize_task.py` calculating legacy scores (1-100), canonical workflow steps (1-12), and resolving task profiles.
  - [x] Implement `scripts/memory/search_memory.py` for exact symbol and lexical keyword index lookups.
  - [x] Create Yaml workflow definitions in `workflows/` (`chat.nano.yaml`, `code.small.yaml`, `architecture.giant.yaml`).
- [x] **Root Index Maintenance**: Keep [llms.txt](file:///Users/oleksii/Documents/News%20Research%20Automation/llms.txt) up to date with new blueprints and services.
- [x] **Task Experience Log**: Document every completed task, obstacle, and code regression inside [task_capsules.jsonl](file:///Users/oleksii/Documents/News%20Research%20Automation/agent_context/task_capsules.jsonl).
- [x] **Retrieval Router Optimization**: Integrate exact symbol lookups, semantic vector matches, and code graph parsing into RAG queries.
- [x] **OS-Inspired Memory Lifecycle**: Add node/edge/event manifests, worker isolation summaries, and validator status transitions for trusted memory updates.
- [x] **Method Log Review API**: Add protected `/api/analytics/data-methods`, `POST /api/analytics/data-methods/review`, and scheduler-friendly `method-review` snapshot command.
- [x] **Memory OS Control-Plane Audit**: Add `scripts/memory/audit_memos.py` to summarize handoff, capsules, lifecycle files, roadmap status, and next recommendations.
- [x] **Portable Memos CLI**: Add `scripts/memos.py` with `init`, `integrate`, `audit`, `validate`, and `snapshot` commands for project-local Memory OS operations.
- [x] **Periodic Method Log Review Proposal Loop**: Convert repeated `method-review` insights into deduplicated admin proposals with dry-run default and optional lifecycle event logging.
- [x] **Workflow Quantizer Alignment**: Align `quantize_task.py`, workflow TOML specs, and `scripts/memos.py quantize` with the 12-step Memory OS contract while preserving legacy 1-100 scoring.
- [x] **Workflow Manifest Validation**: Validate workflow TOML specs for required fields, 12-step coverage, overlap, model policy, and generate `memory/workflow_manifest.json`.
- [x] **Proposal Metadata Contract**: Define lightweight proposal defaults for `product` / `memory_os`, automated site feedback, method-review proposals, developer-owner authority, and future `master_admin` / `admin` / `user` roles without adding a DB migration or full RBAC layer.
- [x] **Approved Scheduler Binding**: Choose a manual, launchd, cron, or dashboard-triggered cadence for `method-review` / `method-proposals`; do not run background daemons without explicit approval (Option S1 manual dashboard trigger button implemented).
