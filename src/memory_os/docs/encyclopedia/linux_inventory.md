# Linux Inventory Integration

This is a platform-specific adapter, not a core Memory OS requirement. Linux/Ubuntu
is the current development and provisioning profile; the memory engine itself must
remain portable to macOS, with Windows deferred until dedicated platform adapters
are justified by product maturity.

Memory OS can maintain a compact Linux/Ubuntu inventory in the memory runtime so
agents can answer operational questions without repeatedly dumping terminal
state into prompt context.

## Commands

```bash
python -m memory_os linux inventory --write
python -m memory_os linux sync
python -m memory_os linux query "ollama"
python -m memory_os linux doctor
```

`inventory` is read-only. `sync` writes verified `domain=linux_inventory` facts
to `memory/nodes.jsonl`, `memory/edges.jsonl`, and the SQLite index.

## Scope

The collector records:

- OS, kernel, CPU, RAM, filesystems.
- APT manual packages and DPKG installed packages.
- Common binaries used by agents and local development.
- systemd user services.
- Docker containers when the user has socket access.
- Ollama HTTP API and local models.
- NVIDIA/GPU health.
- Listening ports.
- Git repositories under `~/dev` and `~/Projects`.
- GGUF model files under `~/models`.

## Safety Model

The collector does not run sudo and does not mutate system state. It may report
commands that would require sudo, but agents must ask the user first and explain
the change in one sentence before running them.

Read-only inventory can run autonomously through a user timer:

```bash
bash scripts/install_systemd_user_services.sh --inventory-only --enable --start
```

The timer runs `memory_os linux sync` after boot and then every 15 minutes.

## State Shape

Inventory facts are stored as `MemoryNode(type="fact", domain="linux_inventory")`
with stable IDs such as:

- `host:memoryos`
- `pkg:apt:docker-ce`
- `container:docker:ollama-memoryos`
- `service:ollama:http:127.0.0.1:11434`
- `model:ollama:qwen3:4b`
- `issue:nvidia-smi`

Edges use `domain=linux_inventory` and connect observed resources back to the
host or their parent service.
