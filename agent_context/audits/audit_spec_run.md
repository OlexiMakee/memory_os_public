# Audit: spec_workflow.py and run_records.py

Scope:
- `src/memory_os/toolkit/spec_workflow.py`
- `src/memory_os/toolkit/run_records.py`

Focus:
- Regex section/field extraction correctness and ReDoS risk.
- Contract write path containment.
- Run record path containment.
- Checkpoint cap/concurrency correctness.
- Resume behavior for terminal runs.

## Findings

### 1. Empty spec title captures the next metadata line

- File: `src/memory_os/toolkit/spec_workflow.py:356`
- Severity: low

`build_contract()` extracts the title with:

```python
re.search(r"^# Spec:\s*(.+)$", spec_text, flags=re.MULTILINE)
```

Because `\s*` includes newlines, an empty title line can consume the line break after `# Spec:` and let `(.+)$` capture the next line. I verified this with a temp spec containing:

```markdown
# Spec:
Status: draft
```

`SpecManager(root).build_contract("001-empty-title")` returned `title == "Status: draft"` instead of falling back to the feature id or returning an empty title.

Suggested fix:
- Replace `\s*` with `[ \t]*` in the title regex.
- Consider anchoring the captured title to same-line non-newline text, for example `r"^# Spec:[ \t]*(.*)$"` plus an empty-string fallback.

### 2. `contract build ..` writes contract files outside `specs/<feature>/`

- File: `src/memory_os/toolkit/spec_workflow.py:339`, `src/memory_os/toolkit/spec_workflow.py:349`, `src/memory_os/toolkit/spec_workflow.py:387`
- Severity: medium

`_resolve_feature()` accepts the explicit selector `..` because `self.specs_dir / ".."` is a directory. `build_contract()` then sets `feature_id` from `feature_root.name`, which is `".."`. `write_contract()` uses that value directly:

```python
feature_root = self.specs_dir / contract["feature_id"]
json_path = feature_root / "contract.json"
md_path = feature_root / "contract.md"
```

I verified that, in a project with at least one spec directory, `SpecManager(root).write_contract("..", force=True)` writes:

```text
specs/../contract.json
specs/../contract.md
```

That creates or overwrites `contract.json` and `contract.md` at the project root, not inside `specs/<feature>/`. This is path traversal out of the intended contract directory.

Suggested fix:
- Validate feature selectors and feature ids with a strict allowlist such as `^[A-Za-z0-9][A-Za-z0-9._-]*$`.
- Reject `"."`, `".."`, path separators, and absolute paths.
- Resolve the candidate path and enforce `candidate.parent == self.specs_dir.resolve()` for direct child specs before reading or writing.

### 3. `build_contract()` crashes with `AttributeError` when no feature can be resolved

- File: `src/memory_os/toolkit/spec_workflow.py:331`, `src/memory_os/toolkit/spec_workflow.py:351`
- Severity: low

`_resolve_feature()` returns `None` when `specs/` does not exist or has no child directories. `build_contract()` does not check that result before passing it to `_paths()`:

```python
feature_root = self._resolve_feature(feature)
paths = self._paths(feature_root)
```

I verified that `SpecManager(root).write_contract("../outside_feature", force=True)` in a temp root with no populated `specs/` raises:

```text
AttributeError: 'NoneType' object has no attribute 'name'
```

The CLI catches `FileNotFoundError` and `ValueError` around `contract build`, but not this crash.

Suggested fix:
- Make `_resolve_feature()` raise `FileNotFoundError` when no feature exists.
- Add a defensive `if feature_root is None: raise FileNotFoundError(...)` in `build_contract()`.

### 4. `run_id` path traversal can read and overwrite `record.json` outside `agent_context/runs`

- File: `src/memory_os/toolkit/run_records.py:45`, `src/memory_os/toolkit/run_records.py:48`, `src/memory_os/toolkit/run_records.py:54`
- Severity: high

`record_path()` joins unvalidated `run_id` directly into the filesystem path:

```python
return self.runs_dir / run_id / "record.json"
```

I verified the escape with a temp config root after ensuring `agent_context/runs` exists:

1. Create an external JSON file at the resolved path reached by `run_id="../../../escape_rr"`:

   ```text
   <root-parent>/escape_rr/record.json
   ```

2. Call:

   ```python
   store.status("../../../escape_rr")
   store.complete("../../../escape_rr", outputs={"pwned": True})
   ```

3. `status()` loaded the external record, and `complete()` rewrote the external `record.json` with `status == "completed"` and `outputs == {"pwned": True}`.

A CLI caller can therefore use traversal segments in `run_id` to read any reachable JSON file named `record.json` and, for mutating commands, overwrite it if the JSON contains a compatible `run_id`.

Suggested fix:
- Validate `run_id` with a strict allowlist matching generated ids, for example `^[A-Za-z0-9._-]+-[0-9a-f]{8}$` if external ids are not required.
- Resolve `self.runs_dir / run_id / "record.json"` and require it to remain under `self.runs_dir.resolve()`.
- Use the originally validated run id for the save path, or separately validate `record["run_id"]` before `_save()`.

### 5. Concurrent checkpoint calls can lose checkpoint data

- File: `src/memory_os/toolkit/run_records.py:83`
- Severity: medium

`checkpoint()` performs an unlocked read-modify-write:

```python
record = self._load(run_id)
checkpoints = list(record.get("checkpoints", []))
checkpoints.append(...)
record["checkpoints"] = checkpoints[-MAX_CHECKPOINTS:]
self._save(record)
```

I verified a two-thread race with an initial record containing 199 checkpoints. Both threads loaded the same record before either saved. Each appended its own checkpoint and saved a 200-item list. The final file still had 200 checkpoints, so the cap did not overflow, but only one of the two new checkpoint steps remained in the file.

Concrete failure scenario:
- Two agents checkpoint `concurrent-A` and `concurrent-B` at the same time for the same run.
- The final `record.json` contains only one of those checkpoint entries.
- The evidence trail silently loses a real step even though both calls returned successfully.

Suggested fix:
- Protect updates with an interprocess file lock around load/append/truncate/save.
- Write via a temp file and atomic rename while holding the lock.
- Add a concurrency regression test that starts from 199 checkpoints and verifies both simultaneous appends are represented or that one call is explicitly rejected/retried.

### 6. `resume()` returns completed and aborted runs instead of rejecting them

- File: `src/memory_os/toolkit/run_records.py:92`
- Severity: medium

`resume()` directly returns `_load(run_id)` without checking status:

```python
def resume(self, run_id: str) -> Dict[str, Any]:
    return self._load(run_id)
```

I verified:

1. `store.start("wf")`
2. `store.complete(run_id)`
3. `store.resume(run_id)` returns a record with `status == "completed"`
4. `store.abort(run_id_2)`
5. `store.resume(run_id_2)` returns a record with `status == "aborted"`

Concrete failure scenario:
- An orchestration layer treats successful `resume()` as permission to continue a run.
- A completed or aborted run is re-entered because `resume()` does not enforce terminal-state rejection.

Suggested fix:
- In `resume()`, reject records whose status is `"completed"` or `"aborted"` with a clear `ValueError`.
- Consider rejecting `"failed"` as terminal too unless the intended model supports explicit failed-run recovery.
- Update CLI handling to catch that `ValueError` and exit non-zero.

## Confirmed Non-Findings

- `src/memory_os/toolkit/spec_workflow.py:431` uses `[ \t]*` in `_section_field()`, so the previously described empty-field/newline capture bug is fixed there.
- I did not find a confirmed ReDoS-prone regex in the scoped `spec_workflow.py` code. The reviewed regexes are either escaped with `re.escape(...)`, bounded to simple character classes, or linear scans over markdown text.
- The final checkpoint file did not exceed `MAX_CHECKPOINTS` in the verified two-writer race because `checkpoint()` truncates with `checkpoints[-MAX_CHECKPOINTS:]` before each save. The confirmed concurrency failure is lost data, not cap overflow.

VERDICT: 6 issues found (1 critical/high)
