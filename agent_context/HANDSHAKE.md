# Active Handoff — 2026-07-01

## Current Session Update — Validation and Multiplexer Alignment (2026-07-01)

- Active Orchestrator: Antigravity (AI coding assistant by Google DeepMind team).
- Status: Doctor and Validation fully operational, 145 tests passed.
- Accomplishments & Fixes:
  1. **Evidence File Path Fix in nodes.jsonl**:
     - Fixed `nodes.jsonl` line 29 where the evidence referenced `src/memory_os/toolkit/tmux_manager.py` (which was renamed to `src/memory_os/toolkit/multiplexer_manager.py`).
     - Successfully validated all structures via `memory_os validate` (exits 0 now).
  2. **Doctor Verification**:
     - Confirmed background daemon is RUNNING (PID 64720).
     - SQLite DB contains 383 active nodes.
     - Local Ollama `gemma3:4b` is fully reachable.
  3. **Diagnostic Test Suite**:
     - Ran the comprehensive test suite (`pytest tests`); all 145 tests passed successfully.

## Current Session Update — Combined Agent Response Tracking (2026-06-28)

- Active Orchestrator: Claude (claude-sonnet-4-6).
- Task: Combined 3-layer tracking for swarm task completion.
- Status: Implemented and verified. All tests pass.
- Key Changes:
  1. **`agent_comm.py` `_write_done_signal()`** (new method):
     - Called automatically in `send()` when `kind == STATUS_REPORT`.
     - Writes `agent_context/done/{task_id}.json` with sender, message, timestamp.
     - Idempotent (overwrites on duplicate STATUS_REPORT for same task).
  2. **`workspace.py` `watch_task(task_id, root, timeout=300)`** (new function):
     - Polls `agent_context/done/{task_id}.json` every 2s until present or timeout.
     - Calls `_relay_result_to_claude()` — sends done summary to claude's tmux pane.
     - Returns parsed result dict or `{"task_id": ..., "timed_out": True}`.
  3. **`memory_os feed --watch`** (new flag):
     - Tail-f mode on `agent_context/task_events.jsonl` — shows new events as they arrive.
     - Ctrl-C to stop. Formatted output (ts / event / kind / sender / task_id / message).
  4. **`_COMPLETION_PROTOCOL`** updated:
     - Now explains all 3 layers: done file, feed --watch, tmux wake-up.
  - Daemon socket layer: deferred (optional, not GPU-dependent — implement later when daemon mature).
- 3-layer summary:
  - Layer 1 (always): `agent_context/done/{task_id}.json` — file signal for `watch_task()`
  - Layer 2 (always): `agent_context/task_events.jsonl` — visible in `feed --watch`
  - Layer 3 (always): tmux send-keys to claude pane — final answer in current window
  - Layer 4 (future/optional): Daemon Unix socket push
- Verified: `_write_done_signal` unit test passes. `feed --watch` flag registered. `watch_task` imports OK.

## Current Session Update — Workspace Pane Titles Fix (2026-06-28)

- Task: Пейни показували назву бесіди (напр. "review handshake") замість агента.
- Fix: Замінено `select-pane -T` (перезаписується через OSC 2) на custom pane option `@agent_label` (tmux 3.2+, app-proof).
- Формат заголовку: `{agent_id}:{project}` — наприклад `claude:memory_os`, `codex:memory_os`.
- Border format: `#{@agent_label}` — читає custom option, а не terminal title.
- Додано `allow-rename off` щоб команди не перезаписували назву вікна.
- Щоб побачити нові заголовки: треба вбити стару сесію і запустити `memory_os` заново.
- 58 tests pass.

## Current Session Update — Workspace Python Launcher + `memory_os ls` (2026-06-28)

- Active Orchestrator: Claude (claude-sonnet-4-6).
- Task: Replace `scripts/tmux_swarm.sh` with Python, add `memory_os ls`, add daemon dedup guard.
- Status: Implemented and verified. 58 tests pass.
- Key Accomplishments:
  1. **`src/memory_os/toolkit/workspace.py`** (new):
     - `launch_workspace(root)` — reads `registry.toml`, builds per-pane commands dynamically.
     - Layout: `split-window -h` → panes side by side (user confirmed correct).
     - Per cli_agent resume: base command plus registry `launch_flags` (`claude --continue`, `codex resume --last`, `agy --continue`).
     - First local_model from registry → interactive (`ollama run qwen3:4b`).
     - Feed window → `python -m memory_os feed`.
     - `instances(root)` — returns tmux session state + daemon PID liveness.
  2. **`memory_os ls`** (new CLI command):
     - Shows running workspace (tmux) + daemon (PID check via `os.kill(pid, 0)`).
     - `--json` flag. Exit 0 if anything running, 1 if nothing.
  3. **Daemon dedup guard fix** (`cmd_daemon start`):
     - Now validates PID is alive before refusing to start.
     - Removes stale PID file automatically and restarts if process is gone.
  4. **`cli.py` zero-arg path**: calls `launch_workspace()` directly instead of `os.execv(tmux_swarm.sh)`.
- `scripts/tmux_swarm.sh` superseded (kept on disk, no longer called).
- Verified: `.venv/bin/python -m pytest tests` → 58 passed.

## Current Session Update — Zero-Argument `memory_os` Swarm Entrypoint (2026-06-28)

- Active Orchestrator: Antigravity (AI coding assistant by Google DeepMind team).
- Task: Wire zero-argument `memory_os` execution to launch Agent Swarm Dashboard.
- Status: Implemented and verified.
- Key Accomplishments:
  1. **Zero-Argument Swarm Launcher**:
     - Updated `main()` in `src/memory_os/cli.py` to check `if len(sys.argv) == 1:`.
     - Automatically resolves `repo_root / "scripts" / "tmux_swarm.sh"`.
     - When invoked with no subcommands across any Ubuntu terminal (`oleksii@memoryos:~$ memory_os`), seamlessly replaces process via `os.execv` to launch or attach to the interactive `memory_os_workspace` tmux session.
     - Preserves full sub-command and flag CLI usage (`memory_os validate`, `memory_os --help`, etc.).
- Verified Gate Results:
  - `.venv/bin/python -m pytest tests` → 58 passed.
  - `.venv/bin/python -m memory_os validate` → OK.
  - `.venv/bin/python -m memory_os --help` → outputs full clean subcommand help.


## Current Session Update — Agentic OS Phases 6, 7, 8 Implementation & Global Integration (2026-06-28)

- Active Orchestrator: Antigravity (AI coding assistant by Google DeepMind team).
- Task: Architecture Upgrades (Global CLI, Quota Probes, Tmux Swarm Dashboard, Live Feed, Cascade Memory).
- Status: Fully implemented, verified, and integrated into Ubuntu system.
- Key Accomplishments:
  1. **Global Ubuntu Integration**:
     - Symlinked `/home/oleksii/dev/memory_os/.venv/bin/memory_os` to `/home/oleksii/.local/bin/memory_os`.
     - Verified `memory_os` CLI executes globally from any directory across system terminals.
  2. **AgentHealthProbe & Quota Checks (Phase 7)**:
     - Implemented `AgentHealthProbe` in `src/memory_os/toolkit/agent_health.py`.
     - Added CLI command `memory_os agent-registry health [--force] [--json]`.
     - Caches binary status and rate-limit detection in `agent_context/agents/health_cache.json` (gitignored).
     - Integrated lazy health filtering into `RouterPlan._available_agents()` to automatically bypass rate-limited agents.
  3. **Tmux Swarm Dashboard & Custom Process Naming (Phase 8)**:
     - Built `scripts/tmux_swarm.sh` launcher script with duplicate session protection (`tmux has-session`).
     - 2-window layout: `agents` (4 tiled panes with custom program titles `[claude]`, `[codex]`, `[agy]`, `[local-model]`) + `feed` (live communication stream `[live-feed]`).
     - Safe pane navigation configured via `F2` and `Ctrl-B Tab` without breaking terminal shell completion.
  4. **Live Inter-Agent Communication Feed (Phase 4 / 8)**:
     - Implemented `memory_os comm feed` / `memory_os feed` command.
     - Formats merged timeline of all `comm.sent` and inbox messages in human-readable format.
  5. **Cascade Memory Resolution (Phase 6)**:
     - Added `memory_roots` resolution property to `MemoryOSConfig` (supports `MEMORY_OS_ROOTS` env var and `~/.memory_os` global root).
     - Updated `MemorySearcher` in `src/memory_os/modules/search.py` to union nodes across roots with scope tags (`local|project|global`).
- Verified Gate Results:
  - `.venv/bin/python -m pytest tests` → 58 passed.
  - `.venv/bin/python -m memory_os validate` → OK.
  - Inter-agent STATUS_REPORT updates sent to `claude` and `codex` via `memory_os comm`.


## Current Session Update — Claude Code Review task_arch_review (2026-06-28)


- Claude reviewed agy's 4 architecture proposals for task_arch_review.
- Full opinion written to: `agent_context/CLAUDE_REVIEW_task_arch_review.md`
- Recommended implementation order for agy:
  1. AgentHealthProbe (lazy cache in RouterPlan, `health_cache.json`, on-demand CLI)
  2. Tmux Dashboard (2-window layout: "agents" + "feed"; fix Tab → use prefix-Tab or F2)
  3. `memory_os feed` live-feed command (tail task_events + inbox, merged human-readable)
  4. Cascade Memory Resolution (union merge with scope tag; `--root`/`MEMORY_OS_ROOTS`; no auto-create `~/.memory_os/`)
- Key blocking concern from Claude: `bind-key -n Tab` will break shell completion — use `bind-key Tab` (with prefix) instead.
- Run `python -m pytest tests` + `python -m memory_os validate` between each proposal.

## Current Session Update — Codex Context Save (2026-06-28)

- Saved the current discussion state into Memory OS so later agents can resume the philosophy thread without re-deriving the setup.
- Current thread context:
  - `memory_os comm` now uses a file-backed inbox at `agent_context/inbox/<agent>.jsonl`.
  - tmux is only a wake-up signal for interactive sessions.
  - We discussed causal continuity, constrained self-revision, and constitutional authority in the agent identity model.
  - tmux inter-agent pings were tested against sessions `0`, `4`, and `16`; `agy` responded in its pane.
- Current working assumption:
  - `HANDSHAKE.md` is the fast human/agent continuity record.
  - `task_capsules.jsonl` is the append-only machine-readable trail.

## Current Session Update — Antigravity Orchestrator Context (2026-06-28)

- Active Orchestrator: Antigravity (AI coding assistant by Google DeepMind team).
- Key Mandate: Non-stop orchestration and multi-agent tracking over live tmux terminals (`0` for Claude, `4` for Codex, `16` for Antigravity) mirrored in `tmux-dashboard`.
- Enforced Architecture Laws:
  - `rule:mandatory_tmux_communication_only`: All interactive inter-agent communication MUST occur via tmux and `memory_os comm` tooling for 100% transparency.
  - `memory_os comm` module (`src/memory_os/toolkit/agent_comm.py`): File-backed inbox (`agent_context/inbox/<agent>.jsonl`), 500-char bounded payload, strict `TASK_ASSIGN` / `STATUS_REPORT` protocol, and tmux ping execution.
  - Core priorities over UI: shared memory sync (`nodes.jsonl` + SQLite FTS5), local LLM hot-path execution (`llama_cpp` / `Ollama`), and Ubuntu system integration (`memory-os-linux-inventory.timer`).
- Verified Memory Nodes:
  - `fact:antigravity_orchestration_context`
  - `rule:mandatory_tmux_communication_only`
  - `rule:agent_tmux_dashboard_communication`

## Current Session Update — task_a85cf507 Agent Communication Toolkit (2026-06-28)

- Task: `task_a85cf507` — Agent Communication Toolkit (tmux, tmux-dashboard, memory_os comm).
- Status: implemented and verified.
- Protocol refinement after external review:
  - payload is file-backed in `agent_context/inbox/<agent>.jsonl`;
  - tmux is only a wake-up ping (`Escape`/`Enter`), not the payload carrier;
  - `memory_os comm send` now requires `--kind TASK_ASSIGN|STATUS_REPORT` and `--task-id`;
  - message text is normalized and capped at 500 characters.
- Code changes:
  - `src/memory_os/toolkit/agent_comm.py`
    - Added `AgentComm` for tmux-backed inter-agent messaging.
    - `send()` resolves tmux targets from `agent_context/agents/registry.toml` or defaults (`claude` → `0`, `codex` → `4`).
    - `send()` writes the payload into `agent_context/inbox/<agent>.jsonl` and uses tmux only as a wake-up ping.
    - Every send appends a `comm.sent` event to `agent_context/task_events.jsonl`.
    - Successful sends write a compact fact node into `memory/nodes.jsonl` and sync it into SQLite.
    - `inbox()` returns a compact view of matching tasks plus file-backed inbound payloads for low-context agents.
    - `status()` reports tmux availability, target mapping, and recent comm activity.
  - `src/memory_os/cli.py`
    - Added `memory_os comm send|inbox|status`.
    - `send` accepts `--kind`, mandatory `--task-id`, sender/task correlation, and optional tmux override.
    - `inbox` is compact and JSON-capable for small-context agents.
  - Tests added:
    - `tests/test_agent_comm.py`
      - tmux ping sequence + event log + memory sync;
      - inbox combines assigned tasks and file-backed comm payloads;
      - status reports tmux target mapping and recent events.
- Verified commands:
  - `.venv/bin/python -m pytest tests/test_agent_comm.py` -> 3 passed.
  - `.venv/bin/python -m memory_os validate` -> OK.

# Active Handoff — 2026-06-28

## Current Session Update — task_5526cabb Phase 5 Auto-Dispatch Daemon (2026-06-28)

- Task: `task_5526cabb` — Agentic OS Phase 5: Autonomous Task Queue Polling & Auto-Dispatch Daemon.
- Status: implemented and verified.
- Code changes:
  - `src/memory_os/core/daemon.py`
    - Added scheduled daemon task `auto_dispatch_tasks` every 10 seconds.
    - Added `MemoryDaemon.auto_dispatch_tasks(limit=3)`.
    - The daemon scans pending tasks via `TaskKernel`.
    - It routes each task through `RouterPlan`.
    - It skips high-risk / review-required plans without mutating the task.
    - It claims and starts eligible low/medium-risk tasks as `daemon:<agent>`.
    - It dispatches through `DispatcherEngine.dispatch_plan()`.
    - Dispatcher remains responsible for evidence writing and final task transitions.
    - Exceptions during route/dispatch block claimed/running tasks with an `auto-dispatch error` reason.
- Tests added:
  - `tests/test_daemon.py`
    - pending safe task is claimed, dispatched, marked done, and gets evidence;
    - high-risk/review-required task remains pending;
    - dispatch exception blocks the task.
- Verified commands:
  - `.venv/bin/python -m pytest tests/test_daemon.py` -> 3 passed.
  - `.venv/bin/python -m pytest tests` -> 52 passed, 8 existing datetime deprecation warnings.
  - `.venv/bin/python -m memory_os validate` -> OK.

## Current Session Update — task_4446fc16 Ollama HTTP Agent Registry (2026-06-28)

- Task: `task_4446fc16` — Agent Registry Ollama HTTP API Integration & Health Check.
- Status: implemented and verified.
- Goal: local-router/local-responder must be considered available when Docker Ollama HTTP API is reachable at `127.0.0.1:11434`, even if host `ollama` CLI is absent.
- Code changes:
  - `src/memory_os/core/llm_service.py`
    - Added `ollama_http_health(host=None, timeout=1.5)`.
    - Reuses `_discover_ollama_model()` and reports `{ok, host, model, detail}`.
    - Existing `OLLAMA_MODEL` override and 30s model discovery cache remain in place.
  - `src/memory_os/toolkit/router_plan.py`
    - `RouterPlan._available_agents()` now accepts `kind="local_model"` / `command=["ollama", ...]` agents when `ollama_http_health()` succeeds, even if `shutil.which("ollama")` fails.
    - Available local-model agents get `runtime="ollama_http"` metadata.
  - `src/memory_os/cli.py`
    - `memory_os agent-registry audit` now reports `[OK] local-router/local-responder: ollama HTTP ... (CLI not in PATH)` instead of missing CLI when HTTP health passes.
- Tests added/updated:
  - `tests/test_llm_service.py`: Ollama HTTP health parses `/api/tags`.
  - `tests/test_router_plan.py`: local model routing works via Ollama HTTP without CLI.
  - `tests/test_agent_registry.py`: registry audit accepts Ollama HTTP when CLI is absent.
- Verified commands:
  - `.venv/bin/python -m pytest tests` -> 49 passed, 8 existing datetime deprecation warnings.
  - `.venv/bin/python -m memory_os validate` -> OK.
  - Unsandboxed `.venv/bin/python -m memory_os agent-registry audit` -> all agents OK; local-router/local-responder OK through `http://localhost:11434`, model `gemma3:4b`.

## Current Session Update — task_997461ad Local LLM Hot-Path + Shared Memory (2026-06-28)

- Task: `task_997461ad` — Local LLM Hot-Path & Cross-Agent Shared Memory Integration.
- Status: implemented and verified.
- Code changes:
  - `src/memory_os/core/llm_service.py`
    - Added in-process Ollama model discovery cache with 30s TTL.
    - Added `OLLAMA_MODEL` env override so hot-path calls can skip `/api/tags` discovery entirely.
  - `src/memory_os/toolkit/dispatcher.py`
    - `local_model` adapter now calls `DefaultLlmProviderService.call_llm(provider=None, max_tokens=200)` instead of forcing `provider="llama_cpp"`.
    - This restores the intended local-first fallback chain: `llama_server -> llama_cpp -> ollama -> cloud providers`.
    - Added `_sync_shared_memory()` helper.
    - `_write_handoff_memory()` and `_write_task_memory()` now sync `nodes.jsonl` into SQLite `graph_nodes` immediately after writing Memory OS nodes.
- Tests added:
  - `tests/test_dispatcher.py`
    - local_model uses provider auto-fallback (`provider is None`) and bounded `max_tokens=200`.
    - local_model task completion writes evidence and immediately syncs task memory into SQLite `graph_nodes`.
  - `tests/test_llm_service.py`
    - `_discover_ollama_model()` honors `OLLAMA_MODEL` without network access.
- Verified commands:
  - `.venv/bin/python -m pytest tests/test_dispatcher.py tests/test_llm_service.py` -> 19 passed.
  - `.venv/bin/python -m pytest tests` -> 46 passed, 8 existing datetime deprecation warnings.
  - `.venv/bin/python -m memory_os validate` -> OK.

## Current Session Update — task_85cba216 CliAgentAdapter (2026-06-28)

- Task: `task_85cba216` — Implement CliAgentAdapter for Dispatcher.
- Status: implemented and verified.
- User requirement: `claude`, `codex`, and `agy` must run non-interactively through dispatcher subprocesses and write evidence bundles.
- Code changes:
  - Added `CliAgentAdapter` in `src/memory_os/toolkit/dispatcher.py`.
  - `CliAgentAdapter` reads `agent_context/agents/registry.toml`.
  - It uses registry `command` and `dispatch_flags` instead of hardcoding every invocation.
  - Interactive workspace launch uses registry `launch_flags`; non-interactive dispatcher uses `dispatch_flags`.
  - It builds non-interactive commands:
    - `codex`: ensures `codex exec`, adds `-C <repo>`, appends registry flags, then prompt.
    - `claude`: `<command> <dispatch_flags> -p <prompt>`.
    - `agy`: `<command> <dispatch_flags> -p <prompt>` with flags before `-p`.
  - `DispatcherEngine.cli_agent()` now delegates to `CliAgentAdapter`.
  - Real cli-agent dispatch writes evidence under `agent_context/evidence/<task_id>/`.
  - Missing CLI binaries now produce evidence and block the task instead of returning silently without evidence.
  - Dry-run remains non-mutating and does not write evidence.
- Tests added in `tests/test_dispatcher.py`:
  - command construction for `codex`;
  - command construction for `agy`;
  - successful cli-agent subprocess dispatch writes evidence and marks task done;
  - missing binary writes evidence and blocks task;
  - dry-run does not write evidence.
- Verified commands:
  - `.venv/bin/python -m pytest tests/test_dispatcher.py` → 16 passed.
  - `.venv/bin/python -m pytest tests` → 43 passed, 8 warnings.
  - `.venv/bin/python -m memory_os validate` → OK.

## Current Session Update — Linux Inventory Integration (2026-06-28)

- Active objective: integrate Memory OS with Ubuntu/Linux so agents can use a compact knowledge graph of installed packages, services, containers, repos, binaries, ports, models, and host issues instead of repeatedly scanning the machine.
- User requirement: the system should be able to run long tasks autonomously; for sudo/password-required actions it must ask the user with a short, clear explanation of what it is doing.
- Important user reminder: keep this handshake updated so other agents know what changed.
- Current implementation status:
  - Added `src/memory_os/linux_inventory.py`.
  - The collector is read-only by design and suitable for open-source packaging.
  - It collects OS/kernel, CPU/RAM/filesystems, APT/DPKG package sets, common binaries, systemd user services, Docker containers, Ollama HTTP API/models, NVIDIA/GPU health, listening ports, git repos, and local GGUF models.
  - It defines `LinuxFact`, `LinuxInventory`, `LinuxInventoryCollector`, `sync_inventory_to_memory`, `query_inventory`, and snapshot helpers.
  - Sync strategy: replace prior `domain=linux_inventory` nodes/edges, then write verified fact nodes into Memory OS graph and SQLite search index.
  - Added CLI group: `memory_os linux inventory|sync|query|doctor`.
  - Added systemd user units:
    - `memory-os-linux-inventory.service`
    - `memory-os-linux-inventory.timer`
  - Installed and enabled the inventory timer for this Ubuntu user. It runs after boot and every 15 minutes.
  - First timer-triggered sync succeeded: 129 nodes, 128 edges, snapshot at `agent_context/linux_inventory/latest.json`.
- Files already changed in this session:
  - `src/memory_os/linux_inventory.py` (new)
  - `src/memory_os/cli.py` (adds `memory_os linux ...`)
  - `src/memory_os/docs/encyclopedia/linux_inventory.md` (new)
  - `tests/test_linux_inventory.py` (new)
  - `deploy/systemd/user/memory-os-linux-inventory.service.in` (new)
  - `deploy/systemd/user/memory-os-linux-inventory.timer.in` (new)
  - `scripts/install_systemd_user_services.sh` (updated to install timer units)
  - `agent_context/linux_inventory/latest.json` (generated snapshot)
  - `agent_context/audits/ubuntu_inventory_2026-06-28.md` (new)
  - `agent_context/MACHINE_MANIFEST.md` (updated with actual Ubuntu/Ollama/GPU state)
  - `agent_context/HANDSHAKE.md` (this update)
- Pending implementation steps:
  - Consider fixing host `ollama` CLI or agent registry to use the Docker HTTP Ollama API.
  - Fix NVIDIA runtime so `nvidia-smi` works.
  - Decide whether linux inventory nodes should be committed in `memory/nodes.jsonl`, or treated as generated runtime state for public releases.
- Verified commands:
  - `.venv/bin/python -m pytest tests/test_linux_inventory.py` → 3 passed.
  - `.venv/bin/python -m memory_os validate` → OK after schema fix.
  - `.venv/bin/python -m memory_os linux query ollama --limit 5` returns Ollama/container/model facts.
- Current host caveats from latest inventory:
  - Docker container `ollama-memoryos` is running and exposes Ollama API on `127.0.0.1:11434`.
  - Host `ollama` CLI is missing, so agent registry local-router/local-responder reports missing CLI even though the API works.
  - RTX 3060 Ti is present and NVIDIA modules/packages exist, but `nvidia-smi` currently cannot communicate with the driver. Treat GPU runtime as broken until revalidated.
  - Memory OS user services are installed but inactive.
  - `memory_os stats` fails in the active venv because `yaml` is missing.

## Working Directory
- Canonical repo on Ubuntu: `/home/oleksii/dev/memory_os`
- Access from Mac: `ssh memoryos 'cd /home/oleksii/dev/memory_os && <command>'`

## Current Repo State
Working tree clean. All committed and pushed to `origin/main`.

Latest commits:
```
99f5c93 feat: Telegram polling daemon loop + daemon hot-path wiring
2c71896 feat: Agentic OS Phase 1+2 — file-backed Task Kernel + Agent Registry
88be194 feat: dual-LoRA routing — LLAMA_CPP_LORA_RESPONDER for responder role
d06e8cd feat: Ukrainian responder LoRA — dataset, eval suite, CLI source
249ca07 feat: add Telegram and Discord optional adapters + messaging spec
```

## Completed Objectives (A/B/C/D/E/F — all done 2026-06-28)

### A — llama.cpp provider ✅
- `_discover_llama_cpp(lora_role)` / `_call_llama_cpp()` in `src/memory_os/core/llm_service.py`
- Provider chain: `llama_cpp → ollama → gemini → groq → openrouter → openai`
- `LLAMA_CPP_MODEL` (base GGUF), `LLAMA_CPP_LORA` (action adapter), `LLAMA_CPP_BIN` (binary)

### B — Eval hardening ✅
- `agent-action-validity`: 5 cases, synonym lists in `expected_args`

### C — action_router SFT adapter v002 ✅
- `ActionRouterSource` (59 examples), trained Qwen3.5-4B-Base, train_loss=0.6293
- GGUF: `/home/oleksii/models/gguf/action_router_v002.gguf`

### D — Messaging adapters ✅
- `src/memory_os/adapters/telegram_adapter.py` — TelegramAdapter (stdlib urllib)
- `src/memory_os/adapters/discord_adapter.py` — DiscordAdapter (stdlib urllib)
- `agent_context/MESSAGING_ADAPTERS.md` — full spec, routing sketch, security checklist

### E — Ukrainian responder LoRA v001 ✅
- `UkrainianResponderSource` (86 examples), trained Qwen3.5-4B-Base, train_loss=0.8357
- GGUF: `/home/oleksii/models/gguf/responder_v001.gguf` (6.3MB)
- Eval `agent-responder-quality`: 10/10 = 1.0
- Dual-LoRA routing: `LLAMA_CPP_LORA_RESPONDER` env var → `LocalLLMResponder`

### G — Agentic OS Phase 3+4 ✅ (NEW — 2026-06-28)
- `src/memory_os/toolkit/router_plan.py` — RouterPlan (Phase 3)
  - Deterministic routing: capability → kind preference (script/shell/local_model/cli_agent)
  - Budget-aware degradation; promotes fallback when ideal kind unavailable
  - CLI: `memory_os plan [--task-id <id>] [--text "..."] [--risk low|medium|high] [--json]`
- `src/memory_os/toolkit/dispatcher.py` — DispatcherEngine (Phase 4)
  - ShellAdapter, ScriptAdapter, LocalModelAdapter
  - Evidence written to `agent_context/evidence/<task_id>/` (gitignored)
  - Task auto-transitions: ok → done(), fail → blocked(reason)
  - CLI: `memory_os dispatch [--task-id <id>] [--adapter auto|shell|script|local_model] [--dry-run]`
- `src/memory_os/toolkit/handoff_builder.py` — HandoffBuilder
  - Markdown context packs for agent-to-agent transitions
  - CLI: `memory_os handoff build --task-id <id> [--print]`
- `tests/` — 26 tests (task_kernel + router_plan + dispatcher), 26/26 pass

### F — Agentic OS Phase 1+2 ✅ (2026-06-28)
- `src/memory_os/toolkit/task_kernel.py` — TaskKernel (file-backed, JSONL)
  - State machine: pending → claimed → running → blocked → review → done
  - CLI: `memory_os task {create,list,status,claim,start,block,review,done,unclaim,leases,events}`
- `agent_context/agents/registry.toml` — 7 agents: claude, codex, agy, local-router, local-responder, memory-os-cli, shell
  - CLI: `memory_os agent-registry {list,audit}`
- `src/memory_os/adapters/telegram_polling.py` — TelegramPollingDaemon
  - Full loop: get_updates → ActionBrain → Executor → LocalLLMResponder → send_message
  - CLI: `memory_os telegram-daemon [--poll-interval N] [--once]`

## Active .env (daemon startup)
```
LLAMA_CPP_MODEL=/home/oleksii/models/gguf/Qwen3.5-4B-Base.Q4_K_M.gguf
LLAMA_CPP_LORA=/home/oleksii/models/gguf/action_router_v002.gguf
LLAMA_CPP_LORA_RESPONDER=/home/oleksii/models/gguf/responder_v001.gguf
OLLAMA_HOST=http://localhost:11434
```

## To Start Telegram Bot
```bash
cd /home/oleksii/dev/memory_os
TELEGRAM_BOT_TOKEN=<token> python -m memory_os telegram-daemon --poll-interval 2
# Both LoRA adapters activated via .env (auto-loaded by cli.py on startup)
```

## Verified Gates
```bash
python -m memory_os validate
python -m memory_os eval run agent-action-validity --format json
# action: pass_rate=0.80 via llama.cpp+lora, 1.0 via Ollama gemma3:4b
# responder: pass_rate=1.0 (agent-responder-quality, 10/10)
python -m memory_os task create --title "test" --risk low && python -m memory_os task list
python -m memory_os agent-registry list
python -m memory_os telegram-daemon --once   # starts, processes 0 updates, exits 0
```

## Local Model Runtime State

### llama.cpp
- Binary: `/home/oleksii/dev/llama.cpp/build/bin/llama-completion`
- Base GGUF: `/home/oleksii/models/gguf/Qwen3.5-4B-Base.Q4_K_M.gguf` (~2.6GB)
- Action LoRA: `/home/oleksii/models/gguf/action_router_v002.gguf` (6.1MB)
- Responder LoRA: `/home/oleksii/models/gguf/responder_v001.gguf` (6.3MB)
- **Critical:** use `-no-cnv` for base models; without it Qwen3.5 injects `<think>` tokens
- **With LoRA active:** wrap prompt in `<|im_start|>user\n...<|im_end|>\n<|im_start|>assistant\n<think>\n</think>\n`

### Ollama Docker runtime
- Container: `ollama-memoryos`, `http://localhost:11434`
- Pulled: `gemma3:4b` (5/5 eval), `qwen3:4b`, `qwen3-action:4b`
- Fallback when llama_cpp not configured or fails

### Training venv
- `.venv-train` — Python 3.12, torch 2.10.0+cu128, unsloth 2026.6.9, trl 0.24.0
- Convert LoRA: `python /home/oleksii/dev/llama.cpp/convert_lora_to_gguf.py <adapter_dir> --base <hf_snapshot> --outfile <path>.gguf --outtype bf16`
- Download models: `hf download <repo>` (NOT `huggingface-cli` — deprecated)

## Known Limitations
- "Remember this rule: X" → routes to `memory.search` instead of `memory.write` (1 failing case)
  - Root cause: English "Remember" = ambiguous (recall vs store); base model prior at rank=16
  - Fix: increase rank to 32, or rephrase eval case

## Next Priorities (Agentic OS roadmap)
1. **Phase 5 — Daemon + UI integration** — optional daemon that polls task queue, auto-routes, dispatches; UI shows process/task table.
2. **Live Telegram bot** — wire `TELEGRAM_BOT_TOKEN` + `memory_os telegram-daemon`. Each message → creates task → routes → dispatches → responds.
3. **Chat history fine-tuning** — collect real Ukrainian conversations → retrain responder_v002.
4. **CliAgentAdapter** — when user explicitly approves, dispatch to claude/codex/agy for high-risk tasks with evidence writing.

## Full CLI Surface (Agentic OS)
```bash
memory_os task {create,list,status,claim,start,block,review,done,unclaim,leases,events}
memory_os agent-registry {list,audit}
memory_os plan [--task-id X | --text "..." --risk low] [--json]
memory_os dispatch [--task-id X] [--adapter auto|shell|script|local_model] [--dry-run]
memory_os handoff build --task-id X [--print]
memory_os telegram-daemon [--poll-interval N] [--once]
```

## Agent CLI / tmux Notes
- tmux: `/usr/bin/tmux`
- agy: `/home/oleksii/.local/bin/agy`
- claude: `/home/oleksii/.local/bin/claude`
- Non-interactive SSH: use full paths above; `cli-agy`/`cli-claude` not on PATH
- agy shell: flags BEFORE `--print`/`-p`; via subprocess.Popen(list) order doesn't matter
- `scripts/agy_workflow.py` — Python wrapper for agy in subprocess/tmux modes

**Safety boundary:** Do not give agent CLIs `--add-dir /home/oleksii/dev/memory_os` without explicit user consent.

## Do Not Forget
- Run health gates before claiming completion
- Do not leave test writes in `memory/nodes.jsonl` — use temp roots or clean `agent:*` IDs
- `data/` is gitignored — training scripts, datasets, adapters are local only
- Never commit `.env`

---

# Agent Handshake

## Current Session Status
- Updated: 2026-06-27
- Active objective: turn Ubuntu host `memoryos` into the remote MemoryOS agent workstation/server — DONE (smoke tests, hardening backlog, swarm mode all verified). New active objective: stand up and validate the LoRA training pipeline (`src/memory_os/lora/`) on this same host's RTX 3060 Ti — first real end-to-end run DONE (see "LoRA Training Pipeline" section below).
- User preference: work in English, report to user in Ukrainian; move in large batches, don't gate every routine step on confirmation (only genuinely consequential/ambiguous decisions).
- Current working repo on Ubuntu: `/home/oleksii/dev/memory_os`
- Local Mac source repo: `/Users/oleksii/Documents/sandbox/memory_os`

## LoRA Training Pipeline (2026-06-27)
First real GPU training run, closing the loop on the previously interface-only `src/memory_os/lora/` package (built on the Mac, no GPU there).
- Dedicated venv on Ubuntu: `~/dev/memory_os/.venv-train` (kept separate from the main lightweight `.venv`). **Python 3.12, not 3.14** — `dill`/`datasets` is broken on 3.14 (CPython changed `pickle.Pickler._batch_setitems`'s signature; latest `dill==0.4.1` doesn't yet handle it). Installed via `uv python install 3.12` (no sudo needed).
- Stack: `torch` (cu130 for the main `.venv-train` install, then `unsloth` re-pins to its own `torch==2.10.0+cu128` — let it; don't fight unsloth's resolver), `transformers`, `trl`, `peft`, `bitsandbytes`, `accelerate`, `datasets`, `unsloth`.
- Real bug fixed in `src/memory_os/lora/training_config.py`'s SFT template: `unsloth==2026.6.9`/`trl==0.24.0` doesn't auto-handle a raw `"messages"` column — needed an explicit flatten-to-`"text"` step (chat-template-aware, with a manual fallback for base/non-Instruct models with no `chat_template`). Dropped `assistant_only_loss=True` as a side effect — no per-token role metadata survives the flatten, so it would silently no-op; revisit if/when a trl version handles `messages` natively.
- First adapter trained and verified on disk: `docs.lora` v002, base `Qwen/Qwen2.5-Coder-1.5B`, 31 examples from `agent_context/**/*.md`, `train_loss` 2.045, real `adapter_model.safetensors` at `~/dev/memory_os/data/lora/docs_out/adapter/` on Ubuntu (not committed — `data/` is gitignored, this is local runtime state like the rest of `data/`).
- Not yet done: `memory_os eval run agent-action-validity` against this adapter, then `lora registry promote/reject`. Also not yet attempted: `memory.lora`/`terminal.lora` (blocked on real data — `task_capsules.jsonl` is empty and SQLite only has 9 verified nodes on the Mac right now).

## Remote Access
- Ubuntu host: `memoryos`
- Tailscale IP: `100.87.69.110`
- LAN IP: `192.168.0.190`
- Mac SSH alias `memoryos` works with key auth.
- Verified from Mac:
  ```bash
  ssh memoryos 'hostname; whoami; python3 --version'
  ```
  Result: `memoryos`, `oleksii`, `Python 3.14.4`.
- Important: from Mac run `ssh memoryos`; from Ubuntu do not SSH into itself, use `tmux` directly.

## Ubuntu Baseline
- OS: Ubuntu 26.04 LTS, x86_64.
- GPU: RTX 3060 Ti, NVIDIA driver 595.71.05, CUDA 13.2; `nvidia-smi` works.
- Docker CE and Docker Compose are installed and working.
- Tailscale is working for internet SSH access.
- GitHub SSH works for user `OlexiMakee`.
- `uv` is installed in `/home/oleksii/.local/bin` and sourced from `~/.bashrc` / `~/.profile`.
- Rust was installed via `rustup`; verify again if needed with:
  ```bash
  source "$HOME/.cargo/env"
  rustc --version
  cargo --version
  rustfmt --version
  cargo clippy --version
  ```

## Project Transfer
- User transferred all projects from Mac sandbox to Ubuntu `~/dev/`.
- Observed projects:
  - `/home/oleksii/dev/memory_os`
  - `/home/oleksii/dev/News Research Automation`
  - `/home/oleksii/dev/lizards_agent`
  - `/home/oleksii/dev/memory-os-public`
  - `/home/oleksii/dev/memory`
- `News Research Automation` contains private data and `.env`; environment work for it is explicitly deferred.

## MemoryOS Status On Ubuntu
- `.venv` exists in `/home/oleksii/dev/memory_os`.
- Installed with:
  ```bash
  uv venv --python python3 .venv
  source .venv/bin/activate
  uv pip install -e ".[dev,resource-psutil,validation-pydantic]"
  ```
- Validation passed:
  ```bash
  PYTHONPATH=src python -m memory_os validate
  ```
- Doctor passed with all critical paths OK:
  - SQLite DB found at `memory/memory_os.db`
  - Active SQLite nodes: 186
  - Telemetry records: 92
  - LLM API keys / Ollama are not configured yet; this is expected for now.
- Do not debug the UI service now. User explicitly deprioritized UI.

## Git Status / Repo Notes
- Private origin on Ubuntu is SSH:
  ```bash
  git@github.com:OlexiMakee/memory_os.git
  ```
- Commit pushed on Ubuntu:
  ```text
  906bc84 Add Ubuntu bootstrap setup
  ```
- A copied pre-push hook for public sync failed because it referenced the old Mac worktree path. It was disabled on Ubuntu:
  ```text
  .git/hooks/pre-push.disabled-public-sync
  ```
- Do not push private planning/context/data to `memory_os_public`.

## Agent CLI Status
All three agent CLIs were installed and authenticated on Ubuntu.

### Codex
- Version observed: `0.142.3`.
- `codex doctor`: `17 ok`, `0 fail`.
- Smoke passed:
  ```bash
  codex --ask-for-approval never --sandbox read-only exec "Print exactly: codex-ubuntu-ok"
  ```
  Output included: `codex-ubuntu-ok`.
- Note: Codex warned that system `bubblewrap` is not installed and used bundled bubblewrap. Not blocking, but install later:
  ```bash
  sudo apt install -y bubblewrap
  ```

### Claude Code
- Version observed: `2.1.195`.
- Smoke passed:
  ```bash
  claude -p "Print exactly: claude-ubuntu-ok"
  ```
  Output: `claude-ubuntu-ok`.

### Antigravity CLI
- Direct smoke passed:
  ```bash
  agy -p "Print exactly: agy-ubuntu-ok" --print-timeout 2m --dangerously-skip-permissions
  ```
  Output: `agy-ubuntu-ok`.

## Swarm Wrapper Status
Wrapper file:
```text
scripts/swarm_invoke.py
```

### Passed
Codex through wrapper passed:
```bash
python scripts/swarm_invoke.py --target codex --task_id smoke_codex --prompt "Print exactly: swarm-codex-ok" --workdir "$PWD"
```
Output included: `swarm-codex-ok`; task marked completed.

Claude through wrapper passed:
```bash
python scripts/swarm_invoke.py --target claude --task_id smoke_claude --prompt "Print exactly: swarm-claude-ok" --workdir "$PWD"
```
Output included: `swarm-claude-ok`; task marked completed.

Antigravity through wrapper passed (fixed 2026-06-27):
```bash
python scripts/swarm_invoke.py --target agy --task_id smoke_agy --prompt "Print exactly: swarm-agy-ok" --workdir "$PWD"
```
Output included: `swarm-agy-ok`; task marked completed.

Fix applied in `scripts/swarm_invoke.py` (`agy` command now includes `--print-timeout 2m`):
```python
["agy", "-p", prompt, "--print-timeout", "2m", "--dangerously-skip-permissions"]
```
Root cause: without an explicit print-timeout, `agy -p` hung with no output instead of returning after the prompt was answered.

### Current Blocker
None — all three wrapper smoke tests (codex, claude, agy) pass.

## Deferred Work
- UI service/browser refresh issue: defer.
- Ollama/local models: defer until agent CLI orchestration is stable.
- PostgreSQL/Redis/Qdrant: defer until MemoryOS architecture analysis says they are needed.
- News Research Automation environment: defer; record as future plan, latest-first Python 3.14 with fallback only if dependency failures force it.

## Next Agent First Steps
1. On Ubuntu, confirm current location:
   ```bash
   cd ~/dev/memory_os
   source .venv/bin/activate
   ```
2. Run MemoryOS health checks:
   ```bash
   PYTHONPATH=src python -m memory_os validate
   PYTHONPATH=src python -m memory_os doctor
   git status --short --branch
   ```
3. Remote-agent workstation hardening — all items below are done (2026-06-27):
   - `bubblewrap`: already at latest (`0.11.1-1ubuntu0.1`); `codex doctor` now reports `17 ok · 0 warn · 0 fail`.
   - VS Code Remote SSH: documented in `agent_context/VSCODE_REMOTE_SSH.md`.
   - tmux workflow: `scripts/tmux_session.sh` (attach-or-create `memory_os` session, auto cd + venv activate).
   - Machine Manifest: `agent_context/MACHINE_MANIFEST.md` (Mac + Ubuntu host inventory).

## Note On Mac/Ubuntu Git Divergence (resolved 2026-06-27)
- Mac local `main` had fallen behind `origin/main` by one commit (`906bc84`, "Add Ubuntu bootstrap setup") while local disk already had newer uncommitted superset content (systemd section in `UBUNTU_LOCAL_SETUP.md`, `deploy/systemd/`, `install_systemd_user_services.sh`).
- Resolved by committing Mac's working tree (`f590961`) then merging `origin/main` (`498a1bf`), keeping the superset `UBUNTU_LOCAL_SETUP.md` on conflict. Pushed to origin; Ubuntu reconciled the same way and pushed its own merge commit. All three (Mac/Ubuntu/origin) confirmed at the same tree.

## Swarm Mode Run (2026-06-27)
Orchestrated via `SWARM_PROTOCOL.md` directly on Ubuntu (`scripts/swarm_sync.py register` + `scripts/swarm_invoke.py`) to close the hardening backlog in parallel:
- `task_vscode_remote` (claude) → `agent_context/VSCODE_REMOTE_SSH.md` — succeeded first try.
- `task_tmux_polish` (codex) → `scripts/tmux_session.sh` — **first attempt silently no-op'd**: `codex exec` defaults to a read-only sandbox, so the write was rejected but the wrapper still reported `completed` (exit code 0, no rate-limit signal — the wrapper only checks process exit code, not whether the task's actual effect happened). Fixed by adding `--sandbox workspace-write` to the codex command in `scripts/swarm_invoke.py`; re-run succeeded and was verified by checking the file existed on disk, not by trusting the wrapper status.
- `task_machine_manifest` (agy) → `agent_context/MACHINE_MANIFEST.md` — succeeded first try.
- Lesson for next agent: **always verify swarm worker output with an independent `ls`/`git status` check** — `completed` status from `swarm_invoke.py` means "process exited 0 / no rate-limit detected," not "the task's intended file change actually happened."
