---
name: solid-unix-portability-audit
description: Audit Memory OS changes for SOLID boundaries, Unix-style CLI contracts, deterministic automation, and Linux/macOS portability before implementation or review.
allowed-tools:
  - shell
  - git
---

# SOLID Unix Portability Audit

Use this skill for architecture review, broad refactors, CLI additions, and module extraction.

Audit checklist:

1. Single responsibility: no module should mix parsing, persistence, transport, UI, and policy.
2. Open/closed: add backend/adapter interfaces instead of branching through unrelated modules.
3. Dependency inversion: high-level orchestration depends on small contracts, not zellij, Telegram, SQLite, or one CLI implementation.
4. Unix fit: commands have clear stdin/stdout/stderr, exit codes, `--json` where useful, and deterministic behavior.
5. Portability: Linux-first code must not assume Linux-only paths, process APIs, shell features, or desktop services unless isolated behind adapters.
6. No LLM for deterministic work: parsing, hashing, diffing, validation, and routing should be scripts or library code.

When a better path exists, state it before editing. If code changed:

```bash
python3 -m pytest tests/ -x -q
```
