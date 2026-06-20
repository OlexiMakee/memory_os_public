# Upstream Proposal Protocol

Agents using the `public` branch are **forbidden from modifying Memory OS core engine code** directly.
If you find a bug or need a feature, submit it as an upstream proposal.

---

## 1. When to propose vs. when to act locally

| Situation | Action |
|---|---|
| Bug in `memory_os` CLI or core engine | Propose upstream (this doc) |
| Missing flag or CLI improvement | Propose upstream |
| Change to `MemoryNode` / `MemoryEdge` schema | Propose upstream |
| UI visualization improvement | Propose upstream |
| Project-specific logic in your own codebase | Implement locally |
| Workaround inside `data_provider.py` or storage layer | **Do not do this — propose the right abstraction instead** |

---

## 2. How to submit a proposal

### Step 1 — Create a branch

```bash
git checkout -b fix/agent-proposals-YYYY-MM-DD   # for bug fixes
git checkout -b feat/short-description            # for new features
```

### Step 2 — Implement the change

Follow the architecture rules in section 3 below.
Each PR must contain only **independent, self-contained changes**.
If two changes are unrelated, split them into separate commits with clear messages.

### Step 3 — Open a PR against `main`

```bash
gh pr create --base main --title "..." --body "..."
```

PR body must include:
- **What**: one sentence per change
- **Why**: the downstream use case that triggered it
- **Test plan**: concrete commands to verify each change
- **Architecture note**: which layer this touches and why it belongs there

### Step 4 — Do not merge yourself

The human maintainer reviews and merges. Do not self-approve or force-push.

---

## 3. Architecture rules (read before writing code)

### 3.1 Data layer is the single source of truth

All nodes and edges must flow through `MemoryRepository`.

```
✅  repo.get_nodes() → filter → present
❌  data_provider.py reads *.jsonl files directly
❌  UI layer globs memory directory
```

### 3.2 Schema changes must be backward-compatible

Any new field on `MemoryNode` or `MemoryEdge` **must have a default value**.
Existing `nodes.jsonl` files must load without migration.

```python
# ✅ correct — existing files load with default True
indexable: bool = True

# ❌ wrong — breaks existing files that don't have this field
indexable: bool  # no default
```

Always update **both** `from_dict()` and the dataclass field.

### 3.3 Use existing mechanisms before adding new ones

Before adding a new field or flag, check whether the existing schema already covers it:

| Need | Use existing | Do not add |
|---|---|---|
| Skip a node in search/inference | `indexable: bool` field | new file format |
| Mark node as low-confidence | `trust: "inferred"` | new trust level |
| Hide node from graph temporarily | `status: "archived"` | `visible: bool` field |
| Skip a whole type in link-infer | `--exclude-types` CLI flag | type-specific hardcoding |
| Restrict who can create an edge | `Relation Contract Registry` | ad-hoc checks |

### 3.4 Filtering belongs in the data layer, not the presentation layer

```python
# ✅ filter once before any inference
nodes = [n for n in nodes if n.get("indexable", True)]

# ❌ filter inside nested loops in infer_text()
for a in nodes:
    if a.get("type") in excluded:   # O(n²) checks instead of O(n)
        continue
```

### 3.5 New CLI flags must not break existing behavior

- All new arguments must have sensible defaults (existing calls work unchanged)
- `--dry-run` style flags are always safe to add
- Never change argument names or remove existing flags

### 3.6 No hardcoded external tool names in core engine

`swarm_invoke.py` and similar orchestration scripts may reference specific agent CLIs (`claude`, `agy`, `codex`). The **core engine** (`src/memory_os/`) must never do this. If you need pluggable behavior, propose an interface first (`IAgentInvoker`, `IFileLockManager`, etc.) before a concrete implementation.

### 3.7 UI changes must not break filter/search state

The graph holds two datasets:
- `gDataFull` — complete, unfiltered data from the server
- `gData` — filtered view (rebuilt by `applyNodeTypeFilter()`)

UI changes must:
- Never mutate `gDataFull` after initial load
- Call `applyNodeTypeFilter()` after any filter state change
- Persist user settings via `saveSetting()` / `localStorage`

---

## 4. What makes a good proposal

**High value:**
- A concrete downstream problem with a minimal fix
- One logical change per PR (can be multiple files, but one concept)
- Backward-compatible schema additions with `default` values
- CLI flags that filter at the data layer before any LLM call (token economy)
- UI improvements that are purely client-side (no server cost)

**Likely to be rejected:**
- Workarounds that bypass `MemoryRepository` (reading files directly in UI/data layer)
- New parallel data formats (`*_nodes.jsonl`, `*_edges.jsonl`) instead of proper schema fields
- Concrete implementations without interfaces when the behavior should be pluggable
- Features that duplicate lifecycle semantics already expressed by `status` / `trust` / `indexable`
- Changes that make any core module aware of a specific downstream project or agent CLI

---

## 5. Proposal checklist

Before opening a PR, confirm:

- [ ] Change touches only one layer (data / CLI / UI — not mixed without reason)
- [ ] New schema fields have default values and `from_dict()` updated
- [ ] No direct file I/O added outside `MemoryRepository` or `FileSystemMemoryStorage`
- [ ] No existing CLI flag signatures changed or removed
- [ ] `to_dict()` / `from_dict()` round-trip works for new fields
- [ ] Test plan lists concrete `memory_os` commands that verify the change
- [ ] PR title is under 70 characters and describes the change, not the problem
