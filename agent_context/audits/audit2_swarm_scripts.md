# Security and Correctness Code Review Report: Swarm Orchestration Scripts

This report documents the adversarial security and correctness audit of the multi-agent swarm orchestration scripts: `scripts/swarm_invoke.py` and `scripts/swarm_sync.py`.

---

## Scope and Methodology
- **Target Files**:
  - [scripts/swarm_invoke.py](file:///Users/oleksii/Documents/sandbox/memory_os/scripts/swarm_invoke.py)
  - [scripts/swarm_sync.py](file:///Users/oleksii/Documents/sandbox/memory_os/scripts/swarm_sync.py)
- **Focus Areas**:
  - Subprocess invocation safety, shell escape analysis, and prompt/task_id separation.
  - Rate-limit detection logic and susceptibility to false positives or ReDoS.
  - Concurrency safety and lock-holding guarantees for read-modify-write transactions.
  - Input validation of `task_id` and `agent` in filesystem path construction.
  - Subprocess execution timeout policies.

---

## Focus Area Verifications

### (a) Subprocess Invocation Safety
- **Shell Injection & Interpolation**: Verified. [swarm_invoke.py](file:///Users/oleksii/Documents/sandbox/memory_os/scripts/swarm_invoke.py#L76-L83) invokes the agent CLI using `subprocess.Popen` with a list of arguments (`cmd`). No shell interpolation is used, and `shell=True` is not present anywhere in the script.
- **Argument Separation**: The `prompt` text is passed as a separate argv list element (e.g. `cmd = ["claude", "-p", prompt, ...]`). The `task_id` parameter is only used internally to track the status in the backlog; it is **not** passed into the subprocess command line argument list.
- **Verdict**: Zero issues found.

### (d) Filesystem Path Validation for Task & Agent IDs
- **Path Construction Analysis**: Verified. Neither [swarm_sync.py](file:///Users/oleksii/Documents/sandbox/memory_os/scripts/swarm_sync.py) nor [swarm_invoke.py](file:///Users/oleksii/Documents/sandbox/memory_os/scripts/swarm_invoke.py) constructs filesystem paths, directories, or filenames using `task_id` or `agent` variables. They only store them as text fields inside the static JSON files `swarm_backlog.json` and `data/swarm_leases.json`.
- **Verdict**: Zero issues found.

---

## Detailed Audit Findings

### 1. [swarm_invoke.py:73](file:///Users/oleksii/Documents/sandbox/memory_os/scripts/swarm_invoke.py#L73) and [L88-91](file:///Users/oleksii/Documents/sandbox/memory_os/scripts/swarm_invoke.py#L88-91)
* **Vulnerability/Defect**: False Positive Rate-Limit Matches leading to Denial of Service (DoS)
* **Severity**: Medium
* **Concrete Failure Scenario**: 
  The script defines `limit_regex = re.compile(r"(rate\s*limit|quota\s*exhausted|limit\s*exceeded)", re.IGNORECASE)` and scans all subprocess stdout/stderr output lines for matching keywords. 
  If a worker task processes external or user-provided files (e.g., analyzing source code error handlers, compiling telemetry stats, summarizing text, or answering a question about API limits) and echoes these phrases to stdout, `limit_regex.search(line)` triggers immediately. 
  The orchestrator then terminates the worker process midway, updates its status to `"pending_limit"`, and sleeps the task for 2 hours, blocking execution on a false rate-limit match.
* **Suggested Fix**: 
  Avoid checking unstructured output streams for rate limit matches. Instead, rely on standard exit codes (e.g. exit code 429) returned by the agent CLI to determine if a rate limit occurred, or scan only specifically formatted system/API error prefixes instead of the entire stdout/stderr buffer.

### 2. [swarm_sync.py:45](file:///Users/oleksii/Documents/sandbox/memory_os/scripts/swarm_sync.py#L45)
* **Vulnerability/Defect**: Lock Conflict Bypass for Tasks in `pending_limit` Status
* **Severity**: High
* **Concrete Failure Scenario**: 
  When a task is suspended due to rate limiting, `swarm_invoke.py` sets its status to `"pending_limit"`. This status is non-terminal, meaning the task’s file lock leases remain registered in `data/swarm_leases.json` (as they are only cleaned up for `"completed"`, `"failed"`, or `"cancelled"` statuses). 
  However, in `swarm_sync.py:get_active_conflicts`, running tasks are filtered via:
  ```python
  running_tasks = {t["id"]: t for t in backlog if t.get("status") in ("running", "pending")}
  ```
  Since `"pending_limit"` is excluded, the conflict-check algorithm ignores active leases held by rate-limited tasks. 
  If another task requests a lock on the same files, `swarm_sync.py register` will allow it, resulting in multiple concurrent agents working on the same files and causing silent write collisions, race conditions, or file corruption.
* **Suggested Fix**: 
  Include `"pending_limit"` in the set of active statuses checked for conflicts:
  ```python
  running_tasks = {t["id"]: t for t in backlog if t.get("status") in ("running", "pending", "pending_limit")}
  ```

### 3. [swarm_sync.py:26-27](file:///Users/oleksii/Documents/sandbox/memory_os/scripts/swarm_sync.py#L26-27)
* **Vulnerability/Defect**: Silent Database Wipeout on JSON Parse Failure
* **Severity**: High
* **Concrete Failure Scenario**: 
  The shared `locked_json_read_write` context manager contains the following parser fallback:
  ```python
          try:
              f.seek(0)
              content = f.read().strip()
              data = json.loads(content) if content else []
          except Exception:
              data = []
  ```
  If `json.loads(content)` raises any exception (e.g. `json.decoder.JSONDecodeError` due to syntax errors, file corruption, or partial manual editing), the exception is swallowed and `data` is initialized to `[]` (an empty list). 
  When the caller subsequently writes to the file (e.g. registering a task or updating status), the file is truncated and rewritten with the new single task, silently and permanently destroying all other historical task and lease records.
* **Suggested Fix**: 
  Propagate parsing errors so that the execution halts safely rather than silently overwriting the corrupted database:
  ```python
          try:
              f.seek(0)
              content = f.read().strip()
              data = json.loads(content) if content else []
          except json.JSONDecodeError as e:
              raise RuntimeError(f"Database file corruption detected in {file_path}: {e}")
  ```

### 4. [swarm_invoke.py:93](file:///Users/oleksii/Documents/sandbox/memory_os/scripts/swarm_invoke.py#L93)
* **Vulnerability/Defect**: Lack of Subprocess Execution Timeout
* **Severity**: Medium
* **Concrete Failure Scenario**: 
  The invocation script calls `process.wait()` without specifying a timeout. If the spawned worker agent process hangs indefinitely (e.g. entering an infinite loop, blocking on socket I/O, or waiting for terminal input), the orchestrator remains blocked forever. 
  This locks the worker slot and prevents all other tasks in the backlog from execution.
* **Suggested Fix**: 
  Impose a configurable timeout on the execution (e.g., `process.wait(timeout=3600)`) and kill the process if the timeout is exceeded.

---

VERDICT: 4 issues found (2 critical/high)
