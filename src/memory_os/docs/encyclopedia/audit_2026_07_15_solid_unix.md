# SOLID/Unix/Portability Audit — 2026-07-15

Full-codebase audit ordered by Oleksii directly to the swarm ("всім свормом повна ревізія коду
на предмет SOLID, unix, можливих дублів, конфліктів, хардкодінгу — скласти роадмап фіксінгу і
далі рухатись по ньому"). agy started it (spawned a toolkit/ auditor, found ~92 hardcoded
agent-name hits via grep) and hit quota mid-run with no saved output. Restarted from scratch as
4 parallel domain audits (toolkit/, core/, modules/+agent_brain/, cli.py+adapters/+ui/) against
the checklist in `.claude/skills/solid-unix-portability-audit/`. Read-only — no files edited
during the audit itself. ~43k lines / 171 files covered.

Every item below is the auditor's claim. Items marked **[verified]** were independently
re-checked by claude against the live source (grep/read/repro) before being trusted — do the
same before acting on an unverified one if it materially changes scope.

## P0 — Correctness bugs, crashes, write-path integrity (fix first)

1. **[verified]** `dispatcher.py` `CliAgentAdapter.build_command` always appends `-p <prompt>`
   for any non-codex agent, including `"local"`. `local_agent.py`'s argparse only defines
   `--model` — no `-p`/positional prompt (it's an interactive REPL). Any dispatch to `"local"`
   as a `cli_agent` crashes with argparse exit 2. Fix: registry-driven `prompt_flag`/
   `supports_positional_prompt`, or give `local_agent.py` a non-interactive `-p` mode.
   (`toolkit/dispatcher.py:88-109`)
2. **[verified]** Three mutually-contradictory hardcoded zellij pane-index maps in
   `multiplexer_manager.py`: `resolve_pane_target` (`{0:claude,1:codex,2:agy,3:local}`,
   literal duplicated twice in one function), `zellij_defaults` (`codex:1,agy:2,
   agent-manager:4,telegram-chat:5`), `_zellij_default_target` (`codex:2,agy:3,
   telegram-chat:4,agent-manager:5`) — the last two disagree on every index. Root cause:
   `registry.toml` has `tmux_target` but no zellij equivalent. Fix: add `zellij_target` to
   registry.toml, delete the three ad-hoc maps. (`toolkit/multiplexer_manager.py:307,316,334-342,439-447`)
3. **[verified]** `MemoryRepository.add_node/save_nodes/add_edge/save_edges` are marked
   `DeprecationWarning` but still functionally mutate `nodes.jsonl`/`edges.jsonl` directly,
   skip `RelationContractRegistry` validation, write no patch/audit record, trigger no
   `MemorySearcher.incremental_sync`. `ingest_project.py:110,115` calls them live — a real,
   reachable second write path bypassing `RelationPatchStore`, not dead code. The docstring
   claiming these are "called only by RelationPatchStore.apply()" is false — `apply_patch()`
   never calls them. Fix: delete the deprecated methods + private backers, route
   `ingest_project.py` through `RelationPatchStore`/`DomainAdapterIngestor`.
   (`core/repository.py:55-117`)
4. **[verified]** `AstDomainAdapter` and `CodebaseDomainAdapter` in `core/adapters.py` carry
   ~212 lines of byte-for-byte duplicated dependency-graph/clustering logic
   (`build_reverse_dependency_map`, `traverse_dependencies`, `traverse_dependents`,
   `dependency_matches_file`, `resolve_dependency_to_file`, `build_dependency_graph`,
   `compute_god_nodes`, `compute_clusters`, `cluster_node_id`, `cluster_to_node`,
   `cluster_contains_edges` — diffed identical except two default-arg references). This
   predates and is separate from the `parse_to_patches` duplication fixed in commit `07ba4fa`
   — that fix was scoped narrowly and didn't touch this block. Fix: `CodebaseDomainAdapter`
   should delegate these 11 methods to `self.ast_adapter` (same pattern as the `07ba4fa` fix).
   (`core/adapters.py:116-327` vs `464-675`)
5. Two uncoordinated writers materialize the same agent-facing skill file:
   `lifecycle.py:_emit_skill_file` (gated on `verified` status, called from promote/transition)
   vs `exporter.py:PolyglotExporter._export_to_claude` (broader type set, called from
   `compactor.py:500-501,684-685` immediately after building a `status: "draft"` node — i.e.
   *before* any lifecycle verification). Unreviewed LLM-proposed content can become a live,
   always-applied Cursor rule (`.cursor/rules/*.mdc`, `alwaysApply: true`) and Claude skill the
   moment the compactor accepts it, and a later promotion silently overwrites the same file
   with a different schema. Fix: gate all agent-facing materialization on `status == "verified"`
   in one place; delete the unconditional export call from compactor.
   (`modules/lifecycle.py:359-382`, `modules/exporter.py:122-149`, `modules/compactor.py:500-501,684-685`)
6. `ui/data_provider.py:_resolve_file_path`'s rglob fallback returns `found[0]` from an
   unsorted `rglob()` — filesystem glob order isn't guaranteed. If two files share a basename
   in different directories, `/api/read_file` can nondeterministically serve the wrong file's
   contents through a path-confinement boundary function. Fix: `sorted(found)[0]` at minimum,
   or reject ambiguous matches. (`ui/data_provider.py:112-118`)
7. Three independent raw `sqlite3.connect()` sites (`core.py`, `daemon.py:optimize_database`,
   `disk_guard.py:checkpoint_sqlite`), none ever sets `PRAGMA journal_mode=WAL`, all three
   issue `PRAGMA wal_checkpoint(...)` — a silent no-op under the default rollback-journal mode.
   Either WAL was intended and is missing, or these are three duplicated dead pragma calls.
   Fix: decide once in `MemoryOS.get_connection()`, route the other two through it.
   (`core/core.py:39,52`, `core/daemon.py:637,640`, `core/disk_guard.py:255,257-258`)

## P1 — High-severity architecture (DIP/OCP) and silent-failure modes

8. `registry.toml` parsing reimplemented independently in **9+ places**
   (`workspace.py` x3, `daemon_hygiene.py`, `dispatcher.py`, `agent_comm.py`, `router_plan.py`,
   `agent_manager.py`, `skill_registry.py`, `agent_health.py`, `agent_console_scanner.py`).
   4 of them (`daemon_hygiene.py`, `agent_manager.py`, `skill_registry.py`,
   `agent_console_scanner.py`) lack the `tomllib→tomli` fallback the other 5 have — on Python
   <3.11 without `tomli` they silently return an empty registry via a broad `except Exception`.
   Fix: one `load_agent_registry(root)` helper, everyone imports it.
9. tmux/zellij session-alive detection reimplemented independently 3x
   (`workspace_runtime.py`, `multiplexer_manager.py`, `runtime_control.py`'s
   `_stop_tmux_session`/`_stop_zellij_session`) — `RuntimeControl` should call
   `WorkspaceRuntime.status()` instead of reimplementing it.
10. `workspace.py:instances()` only checks tmux, never zellij — under a zellij-runtime
    workspace, `memory_os instances` silently reports nothing running, even though
    `workspace_runtime.py`'s `workspace_runtime_diagnostics()` already does this correctly in
    the same package.
11. `daemon_hygiene.py:reconcile_agent_panes` hardcodes `("claude","codex","agy")` instead of
    deriving from `runtime_health["agents"].keys()` (which is already built from the live
    registry two methods earlier). `bootstrap_installer.py` already lists a 4th known agent
    (`"hermes"`) — if added to registry.toml, ghost-detection/auto-restart silently never
    covers it.
12. Daemon `/space` IPC client implemented independently **3 times**: `cli.py:cmd_switch_space`
    (urllib), `cli.py:cmd_daemon.send_daemon_request` (Unix-socket-first + urllib fallback, a
    more complete client never reused by the first one), `ui/server.py`'s `/api/switch_space`
    handler (a third copy with `except Exception: pass` silently swallowing failures). Single
    strongest concrete duplication in the whole audit — extract one `DaemonClient`.
13. `cli.py:cmd_query` reimplements `MemoryGraphService.list_nodes`'s type/status/trust/tag
    filtering over raw `nodes.jsonl` independently — already drifted (cmd_query has a `--since`
    filter the service lacks; the service has pagination cmd_query lacks).
14. `cli.py:cmd_triage`'s inline `_word_overlap` similarity duplicates, less accurately,
    `MemoryGraphService.get_dedup_candidates` (cosine+jaccard) — triage uses the weaker
    algorithm and never calls the service that already exists for this.
15. `modules/search.py:MemorySearcher.incremental_sync` hand-writes raw SQL
    (`SELECT`/`DELETE`/hand-rolled `INSERT...ON CONFLICT`) directly against SQLite internals
    instead of using `MemoryOS.insert_graph_node()`, which already exists and covers this —
    a query object owns schema/column knowledge it shouldn't.
16. `MemoryDaemon.__init__` unconditionally registers `MockMLEmbeddingAuditor` and
    `MockOllamaAuditor` (explicitly commented "Example Mock Auditors for testing the UI") in
    the real production daemon; their fabricated activity is served verbatim by the public
    `GET /auditors/status` endpoint, indistinguishable from real auditor work.
17. `core/llm_service.py:91` hardcodes a personal absolute path
    (`/home/oleksii/dev/llama.cpp/build/bin/llama-completion`) as the `LLAMA_CPP_BIN` default —
    breaks silently (falls through to `None`, no diagnostic) on any other machine/user.
18. `ui/server.py:do_POST`'s outer `except Exception: self.send_error(500, ...)` swallows every
    unhandled exception from every POST handler with zero logging — server-side failures are
    completely invisible.
19. `ui/server.py`'s `/api/tasks` GET returns HTTP 200 + `[]` on any `TaskKernel` failure,
    indistinguishable from "genuinely no tasks."

## P2 — Medium duplication / hardcoding / SRP debt (real, lower urgency)

20. `PROMOTABLE_NODE_TYPES` redeclared independently 3x (`lifecycle.py` canonical,
    `compactor.py`, `agent_brain/executors.py`) — import the canonical one in both copies.
21. `node_stats.json` read/written independently in `search.py` (writer) and `lifecycle.py`
    (reader) with no shared schema/class — a key rename in one silently breaks the other.
22. `search.py`'s `score += 10.0` "verbatim duplicate" threshold is a bare literal that
    `agent_brain/executors.py:_find_duplicate` also hardcodes (`>= 10.0`) with no shared
    constant tying them — a search-scoring tuning change silently breaks write-time dedup.
23. Cosine similarity thresholds (0.60 semantic / 0.65 default) are literal floats in
    `search.py:275`, not read from `MemoryOSConfig` despite `confidence_threshold` already
    being exactly this kind of tunable config property.
24. `ResourceGuard` thresholds (`max_cpu=75.0, max_ram=85.0, max_temp=80.0`) are hardcoded
    constructor defaults with every call site using no-arg `ResourceGuard()` — not
    config-overridable, unlike `DiskGuard`'s `config.data.get("resources", {})` pattern.
25. `daemon.py` scheduler intervals (9 `add_task` calls) and auto-compaction trigger thresholds
    (`len(uncompacted) >= 3`, `estimated_tokens = len(uncompacted) * 2000`) are magic numbers
    with no config override.
26. `config.py:agent_panes` duplicated as a fallback constant in `workspace.py`;
    `config.py:daemon_port` default `22467` independently hardcoded again in
    `ui_templates/app.js:822` instead of being served from `/status`.
27. Agent name literal `("claude","codex","agy")` hardcoded in **8+ places across cli.py**
    (`1353,2172,4872,5424,5698` + argparse `choices`) plus `adapters/_routing.py`'s
    `agent_map`/fallback, plus `adapters/telegram_polling.py:117` — despite
    `_ordered_cli_agents` already reading the registry correctly as the primary path in one
    place. Ties together with items 8, 11: a single shared "list of live cli_agents" accessor
    would collapse most of these at once.
28. `toolkit/local_agent.py:266,354` hardcode `"python3"` for subprocess dispatch while every
    other module in the codebase correctly uses `sys.executable` — portability gap.
29. ~20 error-print sites in `cli.py` use `print(f"Error: ...")` to **stdout** with `return 1`
    while ~8 correctly use `file=sys.stderr` — inconsistent within the same file, breaks
    `--format json | jq` piping unpredictably depending which command is called.
30. `MEMORY_OS_AGENT_ID` env var default is `"codex"` in `cmd_comm` (`cli.py:1450,1469,1486`)
    but `"claude"` in `cmd_swarm_send` (`cli.py:3689`) — same concept, two silent defaults,
    real message-misattribution risk when the env var is unset.
31. `cli.py:316` hardcodes `http://localhost:11434/api/tags` ignoring `OLLAMA_HOST`, while 6+
    other locations (including `cli.py:4295` itself, later in the same file) correctly read
    `os.environ.get("OLLAMA_HOST", ...)`.
32. `daemon.py` reimplements the same "read+parse a status JSON file, swallow errors" pattern
    3x in one class (`get_status_dict`, `_load_cursor`, `_do_ingest`).
33. `repository.py:sync_graph_nodes/sync_graph_edges` instantiate a fresh `MemoryOS(self.config)`
    on every call (re-running `init_db()`'s schema-creation side effect) instead of using an
    injected handle, and issue raw SQL directly, bypassing `IMemoryStorage`.
34. `daemon.py:_do_ingest` and `daemon.py:auto_compact` hardcode `provider="gemini"` instead of
    routing through the project's own `RoutingPolicy.route()`.
35. `compactor.py` has 3 separate verbatim-duplicated blocks within itself: evidence-cleanup
    dedup logic (`413-417` / `662-666`), snapshot-rebuild (`528-540` / `781-792`, which also
    bypasses `self.storage` via raw `open()`/`json.dump`), and a
    transition+prune+manifest triplet (`514-520` / `774-779`).
36. LLM markdown-fence stripping implemented twice: `compactor.py:_clean_llm_json` (robust) vs
    `persona.py:70-74` (fragile fixed-offset slice `raw_response[7:-3]`, breaks on trailing
    whitespace).
37. `modules/optimizer.py:RouteOptimizer.analyze_metrics` holds a raw hardcoded-table-name SQL
    string against the connection directly — same anti-pattern as `search.py` (item 15).
38. `lifecycle.py:75` re-hardcodes the `confidence_threshold` default `0.7` independently of
    `core/config.py:119`'s own default for the same setting.
39. `compactor.py` hardcodes: resource_mode→batch_size mapping (`347`), 3-critic quorum
    (`[0,1,2]` / `>=2`, `176/186`), and duplicates `step_scale`'s `1..12` range as an
    independent `VALID_STEP_SCORES` literal in `validator.py:188`.
40. `dispatcher.py` repeats the same ~30-line subprocess-run-and-wrap pattern 4x (`shell()`,
    `script()`, `local_model()`, `CliAgentAdapter.run()`).
41. Dead duplicate code `workspace.py:_init_pane`/`_tmux` — never called (verified via grep),
    duplicates the live `TmuxWorkspaceRuntime._init_pane` but lacks its
    `TERM`/`DISPLAY`/`WAYLAND_DISPLAY`/`XAUTHORITY` forwarding. Delete before someone resurrects
    the worse copy.
42. `quota_monitor.py` defines the exact same agent-name-translation dict
    (`{"codex":"Кодекс","claude":"Клод","agy":"Antigravity"}`) twice verbatim in one class.
43. `dispatcher.py:96-109` — the `claude`/`agy` branch and the default `return` are byte-for-byte
    identical (redundant branch); codex's subcommand-insertion quirk should be a registry field
    (`cli_mode`), not a per-agent `if`.
44. "Claude is protected/excluded" logic hardcoded independently in `daemon_hygiene.py:250`
    (ghost-restart protection) and `quota_monitor.py:230` (switch-notification exclusion) —
    should be one registry policy field, not two literal comparisons.
45. `agent_comm.py:_sync_memory` instantiates `MemoryRepository(FileSystemMemoryStorage(),...)`
    fresh inside the transport class on every `send()` call, then runs a full synchronous
    `sync_graph_nodes()` — no injection point, unaccounted latency on every message.
46. `quota_monitor.py:AgentQuotaMonitor` mixes JSON persistence, Telegram transport, ~90 lines
    of hand-rolled date/duration regex parsing, pane control, and task dispatch in one class —
    and reaches into `AgentHealthProbe`'s private `_load_cache`/`_save_cache`/`_load_registry`
    across the class boundary (broken encapsulation, not just an SRP smell).
47. `agent_comm.py:AgentComm` (~40 methods) combines transport, file-backed persistence +
    rotation, memory-graph sync, an interactive-prompt state machine, and read-side query APIs
    in one class.
48. `toolkit/workspace.py` (whole file) is an unstructured free-function grab-bag: registry
    parsing, tmux transport, prompt-file mutation on disk, task delivery, status checking — no
    class boundaries.
49. `adapters/_dispatch.py:_dispatch` is a 240-line nested closure combining dedup hashing,
    worktree lifecycle, task-kernel creation, message templating, polling, and cascading
    failover in one method.
50. `adapters/_routing.py:process_update` does update parsing, task-kernel create/claim/start,
    orchestrator invocation, responder invocation, Telegram send, task-kernel close, and
    training-data logging — 5+ responsibilities, each independently try/except-wrapped.
51. `cli.py:cmd_daemon` hand-rolls a full HTTP-over-Unix-socket client inline (raw
    `socket.socket(AF_UNIX)`, manual HTTP/1.1 framing) alongside PID-file lifecycle and output
    formatting — extract a `DaemonClient` transport class.
52. `cli.py:cmd_models` "recommend" branch mixes Ollama HTTP fetch, hardware-fit scoring, and
    manual table rendering in one ~150-line function body with no `--json` escape hatch.
53. `cli.py:cmd_doctor` opens `sqlite3.connect` and runs raw SQL directly in the CLI function
    (also item 15/37's pattern) and has no `--json`/`--format` option despite being the command
    most obviously meant for CI/automated health checks.
54. Private-method cross-module-boundary access: `cli.py:cmd_task` calls
    `kernel._load_leases()`; `adapters/_relay.py` calls `comm._cursor_path`/
    `_load_inbox_messages`/`_save_inbox_cursor`; `adapters/_dispatch.py` calls
    `comm._resolve_tmux_target`. Add public methods on `TaskKernel`/`AgentComm` instead.
55. `root = Path(self.config.root_dir) if hasattr(self.config, "root_dir") else Path.cwd()`
    duplicated verbatim **9 times** across `telegram_polling.py`/`_relay.py`/`_routing.py`/
    `_dispatch.py` — `self.config` is always a real `MemoryOSConfig` set once in `__init__`;
    this is defensive handling for an impossible case, which CLAUDE.md's own rules prohibit.
56. `ui/server.py`'s 9 POST handlers (`/api/nodes/verify|update|delete|pin|upsert|archive`,
    `/api/edges/create|upsert|delete`) repeat an identical 4-line read-only-guard/parse/
    empty-check skeleton — collapsible into a small dispatch table.
57. `cli.py:cmd_agent_registry` duplicates the `tomllib`/`tomli` fallback block twice inside the
    same function, with divergent failure behavior between its `list` and `audit` actions.
58. `cli.py:main()`'s bootstrap flow branches on magic string prefixes
    (`"ATTACH:"`/`"KILL_ALL_SESSIONS"`/etc.) and calls `tmux`/`zellij` directly, instead of
    using `workspace_runtime.py`'s `WorkspaceRuntime` abstraction already used correctly
    elsewhere in the same file (`cmd_workspace`).
59. `adapters/_routing.py:101` hardcodes a fragile `parents[4]` ancestor-directory climb to
    locate a fallback registry.toml — breaks if installed to site-packages instead of run from
    a repo checkout.
60. `AlertManager.send_alert()`'s docstring still claims macOS desktop notifications, but the
    actual notification code was removed ("disabled as per user instruction") — it's now a
    second, redundant log sink with a misleading name, since every caller already logs via
    `self.logger` in the same except-block.
61. Three files under `core/` are entirely unreferenced anywhere else in the tree:
    `orchestrator.py` (`TaskOrchestrator.decompose_task`'s docstring claims LLM-backed
    decomposition, but the LLM call is commented out and it unconditionally returns a mock),
    `module_interface.py`, `workflow_manager.py`. Wire them in or delete them.
62. `adapters/_dispatch.py:_local_now_iso()` instantiates a fresh `MemoryOSConfig()` with no
    arguments instead of using `self.config` (already set in `__init__`) — resolves the wrong
    timezone/config if daemon `--root` differs from CWD at call time. Same anti-pattern
    confirmed spreading to `agent_comm.py:943`.
63. `cli.py:cmd_task` "leases" action uses runtime `__import__("datetime")` calls despite
    `datetime`/`timezone`/`UTC` already being imported at the top of the file — no functional
    bug, but signals unfamiliarity with the file's own imports; fix opportunistically.

## Not flagged (checked, found acceptable)

- `agent_brain/` (brain.py, orchestrator.py, executors.py, responder.py, grammar.py,
  vocabulary.py) — comparatively well-structured, correct ABC usage, deterministic
  fast-pathing before LLM calls.
- `history.py`, `timecode_normalizer.py` — clean, single-purpose, correctly use
  storage/patch abstractions; good reference implementations.
- `multiplexer_manager.py`'s `IMultiplexerBackend` split and `workspace_runtime.py`'s
  `WorkspaceRuntime` protocol are genuinely good OCP/DIP examples — the problem is
  `runtime_control.py` and parts of `cli.py`/`multiplexer_manager.py` itself not consistently
  routing through them.
- `link_inferrer.py`'s LLM usage is correctly gated behind an algorithmic cascade and opt-in
  flags — not a "LLM for deterministic work" violation.
- `safe_id.py`, `resource_guard.py` (aside from item 24), `storage.py`, `registry.py`,
  `patch.py`'s core propose/apply/rollback flow, `budget.py`, `write_budget.py`,
  `storage_tier.py`, `queue.py`, `evidence.py`, `disk_guard.py`, `file_policy.py` — well
  isolated, config-driven where it matters.
- `adapters/_routing.py:_parse_swarm_command` — deterministic string matching, a positive
  counter-example worth preserving as the pattern to follow.

## Execution order

P0 items (1-7) first — each is either a live bug/crash or a real integrity/security gap, each
independently verified or small enough to verify before landing. P1 items (8-19) next — real
architectural debt with silent-failure risk, no single fix is huge. P2 (20-63) is real debt but
lower urgency; batch by theme (agent-registry consolidation ties together 8/11/27/42/44; daemon
IPC client consolidation ties together 12; SRP god-class decomposition of `AgentComm`/
`AgentQuotaMonitor`/`MemoryDaemon`/`MemoryCompactor` is the largest-effort, lowest-urgency tier —
do last, and only opportunistically).

Each fix goes through the same review discipline used all session: independent pytest run,
`release-check`, diff read before commit, live verification of anything touching runtime/IPC
paths.
