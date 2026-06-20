# Contribution Proposal Protocol

Use this protocol for reusable Memory OS changes: CLI behavior, core engine code, schema changes, UI behavior, templates, or toolkit workflows.

Project-specific application code should stay in the downstream project. Reusable Memory OS improvements should become a focused issue, proposal, or PR against `OlexiMakee/memory_os_public`.

---

## 1. When to propose vs. when to act locally

| Situation | Action |
|---|---|
| Bug in `memory_os` CLI or core engine | Open a focused issue/PR or proposal |
| Missing flag or CLI improvement | Open a focused issue/PR or proposal |
| Change to `MemoryNode` / `MemoryEdge` schema | Propose first; keep backward compatibility explicit |
| UI visualization improvement | Open a focused issue/PR or proposal |
| Project-specific logic in your own codebase | Implement locally |
| Workaround inside `data_provider.py` or storage layer | Avoid the workaround; propose the right abstraction |

---

## 2. How to submit a change

### Step 1 — Create a branch

```bash
git checkout -b fix/short-description   # for bug fixes
git checkout -b feat/short-description  # for new features
```

### Step 2 — Implement the change

Follow the architecture rules in section 3 below.
Each PR must contain only independent, self-contained changes.
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

### Step 4 — Do not merge yourself unless you own the release decision

The maintainer reviews and merges. Do not self-approve or force-push over review feedback.

---

## 3. Architecture rules (read before writing code)

### 3.1 Data layer is the single source of truth

All nodes and edges must flow through `MemoryRepository`.

```text
OK:  repo.get_nodes() -> filter -> present
BAD: data_provider.py reads *.jsonl files directly
BAD: UI layer globs memory directory
```

### 3.2 Schema changes must be backward-compatible

Any new field on `MemoryNode` or `MemoryEdge` must have a default value.
Existing `nodes.jsonl` files must load without migration.

```python
# OK: existing files load with default True
indexable: bool = True

# BAD: breaks existing files that do not have this field
indexable: bool
```

Always update both `from_dict()` and the dataclass field.

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
# OK: filter once before any inference
nodes = [n for n in nodes if n.get("indexable", True)]

# BAD: repeated checks inside nested loops
for a in nodes:
    if a.get("type") in excluded:
        continue
```

### 3.5 New CLI flags must not break existing behavior

- All new arguments must have sensible defaults.
- `--dry-run` style flags are safe to add.
- Never change argument names or remove existing flags without a migration plan.

### 3.6 No hardcoded external tool names in core engine

Orchestration scripts may reference specific agent CLIs (`claude`, `agy`, `codex`). The core engine (`src/memory_os/`) must not depend on a specific agent CLI. If behavior should be pluggable, propose an interface first (`IAgentInvoker`, `IFileLockManager`, etc.).

### 3.7 UI changes must not break filter/search state

The graph holds two datasets:
- `gDataFull` — complete, unfiltered data from the server
- `gData` — filtered view rebuilt by `applyNodeTypeFilter()`

UI changes must:
- Never mutate `gDataFull` after initial load
- Call `applyNodeTypeFilter()` after any filter state change
- Persist user settings via `saveSetting()` / `localStorage`

---

## 4. What makes a good proposal

High value:
- A concrete downstream problem with a minimal fix
- One logical change per PR
- Backward-compatible schema additions with defaults
- CLI flags that filter at the data layer before any LLM call
- UI improvements that are client-side when possible

Likely to be rejected:
- Workarounds that bypass `MemoryRepository`
- New parallel data formats (`*_nodes.jsonl`, `*_edges.jsonl`) instead of proper schema fields
- Concrete implementations without interfaces when behavior should be pluggable
- Features that duplicate lifecycle semantics already expressed by `status` / `trust` / `indexable`
- Changes that make core modules aware of a specific downstream project

---

## 5. Proposal checklist

Before opening a PR, confirm:

- [ ] Change touches only one layer unless cross-layer work is justified
- [ ] New schema fields have default values and `from_dict()` updated
- [ ] No direct file I/O added outside `MemoryRepository` or `FileSystemMemoryStorage`
- [ ] No existing CLI flag signatures changed or removed
- [ ] `to_dict()` / `from_dict()` round-trip works for new fields
- [ ] Test plan lists concrete `memory_os` commands that verify the change
- [ ] PR title is under 70 characters and describes the change, not the problem
