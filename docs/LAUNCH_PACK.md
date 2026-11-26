# Memory OS v0.2.0 — Public Launch Pack

Technical launch copy, MCP directory metadata, and release checklist for **Memory OS** (`memory-os` v0.2.0, MIT Core).

---

## 1. Show HN

### Title
`Show HN: Memory OS – Git-native JSONL/FTS5 memory and CI evidence gate for coding agents`

### Body
I built Memory OS (`pip install memory-os`, MIT core) to solve two failure modes I kept hitting with Claude Code, Cursor, and Codex:

1. **Black-box cloud memory:** Most agent memory layers burn an LLM call on every write, store opaque embeddings in a SaaS DB, and drift without any git history.
2. **The AI PR "first-pass illusion":** Coding agents report a task done with green-looking tests that have no assertions, swallow exceptions with bare `except:`, or never actually ran the test command.

Memory OS replaces both with a deterministic, zero-dependency Python 3.9+ stdlib core (`tomli` only on Python < 3.11):

- **Plain-file ground truth + SQLite FTS5:** Architectural facts, policies, and specs live in `memory/*.jsonl` (100% git-diffable, `memory log` / `revert`, lifecycle `draft -> verified`) indexed locally into SQLite FTS5.
- **Least-privilege stdio MCP in 1 command:** `memory-os mcp-install --client claude` (also `cursor`, `codex`) merges the stdio server into `.mcp.json` / `.cursor/mcp.json` / `.codex/config.toml` without overwriting existing servers. Exposes 7 scoped tools (`search_memory`, `build_context_pack`, `read_approved_evidence`, `run_doctor`, `run_resources`, `run_security_scan`, `propose_memory_update`) and explicitly denies shell execution, arbitrary file reads, secret reads, and network fetch.
- **Deterministic CI/PR Evidence Gate:** `memory-os evidence add-command --task <id> -- pytest -q` records command exit codes; the GitHub Action (`memory-os/memory-os@v0.2.0`) blocks merges on missing evidence, leaked secrets, blast-radius overflow, or skeptic-audit findings (empty tests / silent bare-excepts).

**Reproducible local benchmark (`benchmarks/run_proof_benchmark.py`):**

- 1,000 JSONL node writes: **1.98 ms** (0 LLM calls, \$0.00 token cost)
- SQLite FTS5 query latency (200 queries): **p50 0.011 ms / p95 0.013 ms**
- Synthetic defective PR catch rate (missing evidence, leaked secrets, empty-test illusions, silent bare-excepts): **40/40 (100.0%)**

Quickstart:

```bash
pip install memory-os
memory-os init
memory-os mcp-install --client claude
```

Repo: https://github.com/memory-os/memory-os

Happy to answer questions on the JSONL-to-FTS5 sync model, the least-privilege MCP surface, or the AST-based skeptic audit.

---

## 2. Reddit (`r/ClaudeAI` & `r/cursor`)

### Title
`Built a zero-dependency, git-native memory & PR verification layer for Claude Code / Cursor / Codex (MIT, 1-command MCP setup)`

### Body
If you run Claude Code, Cursor, or Codex across multi-day repos, two things break fast:

1. Context files bloat or go stale, while cloud memory tools add network latency, LLM extraction costs on every write, and privacy headaches under NDA.
2. Agents occasionally declare victory on changes where tests were never run, assertions were omitted, or errors were silently caught.

I open-sourced **Memory OS** (`memory-os` v0.2.0, MIT core) to handle both locally with Python stdlib + SQLite FTS5:

- **Git-diffable memory:** Facts, rules, and decisions live in plain `memory/*.jsonl` with lifecycle states (`draft -> verified`), `triage`, `prune`, and `memory revert`.
- **Zero LLM tax on reads/writes:** Measured locally via `benchmarks/run_proof_benchmark.py` — 1,000 JSONL writes take **1.98 ms** and SQLite FTS5 queries run at **0.011 ms p50 / 0.013 ms p95**.
- **1-command MCP setup (non-destructive config merge):**
  ```bash
  pip install memory-os
  memory-os init
  memory-os mcp-install --client claude   # or --client cursor / --client codex
  ```
- **Deterministic verification gate:** Record actual command proofs (`memory-os evidence add-command --task feat-x -- pytest -q`) and run `memory-os security scan` + skeptic audit locally or in GitHub Actions. Catches **40/40** synthetic defective PRs (missing evidence, secret leaks, assertion-free tests, silent bare-excepts).

Everything in the core CLI, local FTS5 search, stdio MCP server, and local pass/fail CI gate is MIT and runs 100% offline.

GitHub: https://github.com/memory-os/memory-os

Feedback welcome — especially on MCP tool ergonomics and what verification checks you want in CI.

---

## 3. Smithery / PulseMCP Directory Metadata

```yaml
name: memory-os
display_name: Memory OS
version: 0.2.0
license: MIT
repository: https://github.com/memory-os/memory-os
homepage: https://github.com/memory-os/memory-os
short_description: >-
  Local-first, git-native JSONL + SQLite FTS5 memory and deterministic
  verification MCP server for Claude Code, Cursor, and Codex. Zero mandatory
  dependencies.
tags:
  - memory
  - sqlite-fts5
  - local-first
  - git-native
  - verification
  - security-scan
  - claude-code
  - cursor
  - codex
  - mcp-stdio
transport: stdio
install:
  pypi: pip install memory-os
  one_command_setup:
    claude: memory-os mcp-install --client claude
    cursor: memory-os mcp-install --client cursor
    codex: memory-os mcp-install --client codex
stdio_server:
  command: python
  args:
    - -m
    - memory_os
    - --root
    - .
    - mcp
capabilities:
  tools:
    - name: search_memory
      description: Search verified and draft Memory OS graph nodes via SQLite FTS5.
      requires_approval: false
    - name: build_context_pack
      description: Build a targeted, reproducible context pack for a task.
      requires_approval: false
    - name: read_approved_evidence
      description: Read latest deterministic verification evidence bundle status.
      requires_approval: false
    - name: run_doctor
      description: Run local Memory OS health and configuration diagnostics.
      requires_approval: false
    - name: run_resources
      description: Capture local disk, SQLite, and JSONL resource telemetry snapshot.
      requires_approval: false
    - name: run_security_scan
      description: Scan local memory and docs for secret leaks and prompt-injection markers.
      requires_approval: false
    - name: propose_memory_update
      description: Propose a draft memory node into Memory OS (gated by approved=true).
      requires_approval: true
  denied_by_default:
    - arbitrary_shell
    - arbitrary_filesystem_read
    - destructive_graph_write
    - raw_telemetry_read
    - secret_read
    - network_fetch
```

---

## 4. PyPI & GitHub Marketplace Release Checklist (`v0.2.0`)

### A. Pre-Flight Verification
- [ ] Confirm `pyproject.toml` version is `0.2.0` and `dependencies` remain stdlib-only (`tomli>=1.1.0; python_version < '3.11'`).
- [ ] Run full test suite: `python -m pytest tests/ -q` (100% pass, exit 0).
- [ ] Re-verify benchmark reproducibility: `python benchmarks/run_proof_benchmark.py --format markdown`.
- [ ] Verify Clean-Room export & gate:
  ```bash
  python scripts/build_public_release.py --out /tmp/memory_os_public --build-wheel
  ```
  Confirm output reports `Clean-Room Export: PASS` with `[OK] public-clean-room`, `[OK] core-dependencies`, `[OK] public-private-files`, and `.whl` artifact generated under `/tmp/memory_os_public/dist/`.

### B. PyPI Publish
- [ ] Build source distribution (`sdist`) inside `/tmp/memory_os_public` alongside the wheel:
  ```bash
  python -m build /tmp/memory_os_public --outdir /tmp/memory_os_public/dist
  ```
- [ ] Validate metadata and long description:
  ```bash
  twine check /tmp/memory_os_public/dist/*
  ```
- [ ] Smoke-test upload on TestPyPI first:
  ```bash
  twine upload --repository testpypi /tmp/memory_os_public/dist/*
  ```
- [ ] Install wheel in a clean ephemeral venv and verify `memory-os --help`, `memory-os init`, and `memory-os mcp-install --client claude --dry-run`.
- [ ] Publish to production PyPI:
  ```bash
  twine upload /tmp/memory_os_public/dist/*
  ```

### C. GitHub Repository & GitHub Marketplace Action (`v0.2.0`)
- [ ] Push clean-room staging tree to the public `memory-os/memory-os` repository `main` branch.
- [ ] Verify `action.yml` metadata (`name`, `description`, `branding`, `inputs`, `outputs`) and default runner invocation.
- [ ] Create and push annotated release tag:
  ```bash
  git tag -a v0.2.0 -m "Memory OS v0.2.0 — Public Core & CI Verification Gate"
  git push origin v0.2.0
  ```
- [ ] Create GitHub Release for `v0.2.0`, attach release notes with benchmark table, and check **"Publish this Action to the GitHub Marketplace"**.
- [ ] Submit MCP listing to Smithery and PulseMCP using Section 3 metadata.
- [ ] Post Show HN and Reddit threads once PyPI install and GitHub Action tag `v0.2.0` are live.
