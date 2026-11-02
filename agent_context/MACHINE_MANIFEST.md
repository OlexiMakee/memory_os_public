# Memory OS Machine Manifest

This document outlines the known development and runtime hosts for Memory OS.

## 1. Mac Dev Machine

- **Role**: Primary source of truth / primary development machine
- **Repo Path**: `/Users/oleksii/Documents/sandbox/memory_os`
- **OS / Hardware**: macOS (Mac dev machine)
- **What is Installed**: Primary development workstation environment
- **How to Reach It**: Local workstation

## 2. Ubuntu Remote Agent Workstation

- **Role**: Remote agent workstation / runtime execution host
- **Repo Path**: `/home/oleksii/dev/memory_os`
- **OS / Hardware**: Ubuntu 26.04 LTS; AMD Ryzen 9 7900X; 30 GiB RAM; GPU NVIDIA GeForce RTX 3060 Ti LHR
- **What is Installed**:
  - Docker CE
  - Agent CLIs (`codex`, `claude`, `agy` - all installed and authenticated)
  - Ollama is running in Docker as `ollama-memoryos` on `127.0.0.1:11434`; host `ollama` CLI is not installed
  - Local Ollama models: `gemma3:4b`, `qwen3:4b`, `qwen3-action:4b`
  - Systemd user services (`memory-os-ui.service` and `memory-os-daemon.service`, available via `scripts/install_systemd_user_services.sh`)
- **Current Caveats**:
  - As of 2026-06-28, NVIDIA 595 packages and kernel modules are present, but `nvidia-smi` cannot communicate with the driver. Treat GPU runtime as broken until revalidated.
  - Memory OS user services are installed but inactive.
  - See `agent_context/audits/ubuntu_inventory_2026-06-28.md` for the latest inventory.
- **How to Reach It**:
  - SSH Alias: `memoryos`
  - Tailscale IP: `100.87.69.110`
  - LAN IP: `192.168.0.190`
