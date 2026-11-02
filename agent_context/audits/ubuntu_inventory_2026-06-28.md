# Ubuntu Inventory Audit - 2026-06-28

## Scope

Inventory was collected on the Ubuntu remote agent workstation using Memory OS
diagnostics plus local system commands. No secret files were opened.

## Memory OS Instrumentation

- `memory_os validate`: OK.
- `memory_os doctor`: all critical paths OK.
- Memory graph: 186 active SQLite nodes.
- Telemetry records: 92.
- Memory OS daemon/UI user services: installed but inactive.
- `memory_os resources snapshot`: level `cool`; free disk about 379716 MB; JSONL total about 1.42 MB; SQLite DB about 0.25 MB; WAL 0 MB.
- `memory_os storage advise`: recommended tier is `sqlite`.
- `memory_os adapters audit`: `telegram=True`, `discord=True`; ollama/litellm/markitdown/otel/duckdb/qdrant/phoenix/langfuse/mlflow/pydantic_ai/vllm/mcp unavailable in the active venv.
- `memory_os provider list`: ollama configured but Python package/host CLI not installed; groq package installed but not configured.
- `memory_os agent-registry audit`: `claude`, `codex`, `agy`, `memory-os-cli`, and shell OK; local-router/local-responder missing because `ollama` CLI is not in PATH.
- `memory_os stats`: fails in the active venv because module `yaml` is missing, despite system `python3-yaml` being installed.

## Host

- Hostname: `memoryos`.
- OS: Ubuntu 26.04 LTS `resolute`.
- Kernel: `7.0.0-27-generic`.
- CPU: AMD Ryzen 9 7900X, 12 cores / 24 threads.
- RAM: 30 GiB total; about 28 GiB available at audit time.
- Swap: 8 GiB.
- Main disk: Kingston SKC3000D2048G, 1.9 TB NVMe.
- Ubuntu root: `/dev/nvme0n1p6`, ext4, 480G size, 85G used, 371G available.
- Additional NTFS partitions are present, likely Windows/data partitions.

## GPU And Acceleration

- PCI GPU: NVIDIA GA104 GeForce RTX 3060 Ti Lite Hash Rate.
- Installed NVIDIA package family: `595-server-open`, including `nvidia-utils-595-server`.
- Kernel modules are loaded: `nvidia`, `nvidia_uvm`, `nvidia_modeset`, `nvidia_drm`.
- Current issue: `nvidia-smi` fails with "couldn't communicate with the NVIDIA driver".
- `nvcc` is not installed.
- `nvtop` is installed.
- Local CUDA/GPU usability should be treated as broken until `nvidia-smi` works.

## Containers And Local Models

- Docker CE: 29.6.1.
- Active container: `ollama-memoryos`, image `ollama/ollama:latest`, restart policy `unless-stopped`.
- Container bind: `/home/oleksii/.ollama:/root/.ollama`.
- Ollama API is exposed on `127.0.0.1:11434`.
- Host `ollama` CLI is not installed.
- Ollama models exposed by API:
  - `gemma3:4b`, 4.3B, Q4_K_M.
  - `qwen3:4b`, 4.0B, Q4_K_M, tools/thinking, 262144 context.
  - `qwen3-action:4b`, derived from `qwen3:4b`, tools/thinking, 262144 context.
- Local GGUF files in `/home/oleksii/models/gguf`:
  - `Qwen3.5-4B-Base.Q4_K_M.gguf` about 2.7 GB.
  - `action_router_v001.gguf`, `action_router_v002.gguf`, `responder_v001.gguf`, small adapter-like artifacts.

## Networking And Services

- Listening TCP ports:
  - `0.0.0.0:22` and `[::]:22` for SSH.
  - `127.0.0.1:11434` for Ollama API.
  - Tailscale-related listeners on `100.87.69.110` and IPv6 Tailscale address.
- Tailscale package installed: 1.98.4.
- Memory OS user services are installed but inactive:
  - `memory-os-ui.service`
  - `memory-os-daemon.service`

## Developer Tooling

- Agent CLIs:
  - `codex` 0.142.3.
  - `claude` 2.1.195.
  - `agy` 1.0.13.
- `tmux-dashboard` installed in `/home/oleksii/.local/bin`.
- Python: 3.14.4.
- `uv`: 0.11.25.
- Git: 2.53.0.
- Rust: `rustc`/`cargo` 1.96.0.
- Docker, buildx, compose plugin installed.
- C/C++ tooling: build-essential, clang 21, cmake 4.2.3, ninja, gdb, lldb, valgrind, ccache.
- Node.js/npm are not installed on host.

## Local Project Footprint

- `/home/oleksii/dev`: about 35G.
- Main checkouts:
  - `memory_os`: about 11G, including `.venv-train` about 9.3G and `data` about 1006M.
  - `News Research Automation`: about 25G, dominated by `.git` about 22G and `data` about 2.2G.
  - `llama.cpp`: about 307M.
  - `lizards_agent`: about 35M.
  - `memory-os-public`: about 3.2M.
- `/home/oleksii/models`: about 2.6G.

## Gaps / Follow-Up

- Fix NVIDIA runtime: packages and modules exist, but `nvidia-smi` cannot talk to the driver.
- Install or shim host `ollama` CLI if Memory OS local-router/local-responder should use CLI execution instead of HTTP/container access.
- Add `PyYAML` to the active Memory OS venv or adjust `memory_os stats` dependency declaration.
- Consider adding the user to the `docker` group if non-escalated Docker access is desired; current group list does not include `docker`.
- `snap list` did not return within 40 seconds and was interrupted.
