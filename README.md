# Memory OS

**Git-native Memory & Deterministic Verification Control Plane for AI Coding Agents (Claude Code, Cursor, Codex).**

Zero mandatory external dependencies. 100% local-first. Plain-file `JSONL` ground truth + `SQLite FTS5` search + merge-blocking CI/PR Evidence Gates.

---

## Why Memory OS?

| Pain Point (AI Coding Agents in 2026) | Cloud Vector Memory / Noisy AI Reviewers | **Memory OS** |
| :--- | :--- | :--- |
| **Black-box debugging** | Cannot see why the agent hallucinated | Plain-text `memory/*.jsonl` (100% git-diffable) + `memory log / revert` |
| **Token burn & latency** | LLM call on every memory write | Deterministic local writes + `SQLite FTS5` (0ms LLM latency) |
| **Memory pollution** | Stale logs & junk pile up | Lifecycle (`draft -> verified`), `triage`, `prune`, `security scan` |
| **Privacy / NDA / GDPR** | Uploads proprietary code to external SaaS | **100% Local-First** — CLI, MCP, and CI Gate run inside your own machine/runner |
| **AI PR "First-Pass Illusion"** | Rubber-stamped PRs with no proof tests ran | **Deterministic Evidence Gate** blocks merge unless commands actually passed |

---

## 60-Second Quickstart

```bash
# 1. Install (Python 3.9+, zero mandatory dependencies)
pip install memory-os

# 2. Initialize plain-file memory & spec structure in your repo
memory-os init

# 3. Connect stdio MCP to Claude Code, Cursor, or Codex in 1 command
memory-os mcp-install --client claude
memory-os mcp-install --client cursor
memory-os mcp-install --client codex
```

### Core Daily Workflow

```bash
# Search project memory & codebase symbols
memory-os search "authentication"

# Record an architectural fact or policy
memory-os memory write --type fact --summary "Use SQLite WAL mode for local index"
memory-os sync

# Enforce deterministic command evidence before marking a task done
memory-os evidence init --task feat-auth --risk-class medium
memory-os evidence add-command --task feat-auth -- pytest -q
memory-os evidence verify --task feat-auth

# Run local security & hygiene checks
memory-os security scan
memory-os doctor
```

---

## CI/PR Verification Gate (GitHub Action)

Block AI-generated pull requests that lack verified command evidence, leak secrets, or exceed blast-radius limits — **running 100% inside your GitHub Actions runner**:

```yaml
name: Memory OS Verification Gate
on: [pull_request]

jobs:
  verify:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
      security-events: write
    steps:
      - uses: actions/checkout@v4
      - uses: memory-os/memory-os@v0.2.0
        with:
          require-evidence: "true"
          max-changed-files: "10"
          sarif-file: "memory-os-security.sarif"
          license-key: ${{ secrets.MEMORY_OS_LICENSE_KEY }}
```

### Open-Core Tiers (Flat Pricing — No Per-Seat Tax)

* **Core (`MIT` — Free forever):** Local CLI, `JSONL + SQLite FTS5`, `stdio` MCP, `spec`, `evidence`, `security scan`, local CI pass/fail gate.
* **Pro Solo:** Native **SARIF 2.1.0** export to GitHub Security, local Web Graph UI, multi-repo search.
* **Team CI Gate (Flat per org — unlimited committers):** Automated Markdown PR Verification Comments, custom blast-radius & policy enforcement, audit logs.
* **Enterprise Offline:** Air-gapped signed license tokens (`LIC1.*`) for isolated VPC/EU runners.

Manage licenses via CLI:

```bash
memory-os license status
memory-os license activate <YOUR_KEY>
```

---

## License

Core repository is licensed under the **MIT License**. See [PRODUCT_BOUNDARY.md](PRODUCT_BOUNDARY.md) for the Open-Core boundary.
