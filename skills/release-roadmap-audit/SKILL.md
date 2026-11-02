---
name: release-roadmap-audit
description: Audit Memory OS roadmap, docs, changelog-like summaries, commits, and release readiness by comparing shipped code against documented strategy and user-facing CLI behavior.
allowed-tools:
  - shell
  - git
---

# Release Roadmap Audit

Use this skill before pushing, publishing install instructions, or declaring a roadmap phase done.

Process:

1. Determine the commit range or changed files:
   ```bash
   git status --short
   git log --oneline -20
   ```
2. Compare changed user-facing behavior against:
   - `README.md`
   - `src/memory_os/docs/encyclopedia/cli_tools.md`
   - `src/memory_os/docs/encyclopedia/roadmap.md`
   - install/bootstrap docs
3. Check whether new CLI commands have docs, tests, clear exit codes, and JSON mode when automation needs it.
4. Flag stale roadmap claims, undocumented behavior changes, and release gates weakened for convenience.
5. Keep the report short: readiness, missing docs/tests, risky changes, required next action.

Run:

```bash
python3 -m pytest tests/ -x -q
python3 -m memory_os release-check
```

If `release-check` is unavailable or blocked, state the reason.
