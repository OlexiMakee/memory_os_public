# Resource Bounds and Telemetry Security Audit Report

This report details the findings from an adversarial security and correctness code review of the following files:
1. [disk_guard.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/disk_guard.py)
2. [telemetry_policy.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/telemetry_policy.py)
3. [telemetry.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/telemetry.py)

---

## Findings

### Finding 1: Path Traversal/Project Root Escape via Config Paths
* **File:Line:** [config.py:55-106](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/config.py#L55-L106) (affecting [disk_guard.py:96](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/disk_guard.py#L96) and [telemetry_policy.py:59](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/telemetry_policy.py#L59))
* **Severity:** High
* **Failure/Exploit Scenario:**
  The configuration parser constructs paths like `db_path` and `memory_dir` using `(self.root_dir / val).resolve()` without validating that the resolved path is a descendant of `self.root_dir`.
  If a user configuration file contains `"db_path": "../../../../../etc/shadow"` or an absolute path like `"/etc/shadow"`, the path will resolve outside the project root.
  - In [disk_guard.py:96](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/disk_guard.py#L96), `DiskGuard` will fetch the file size of `/etc/shadow` and attempt to read it via stat calls, leaking file size details.
  - In [core.py:22](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/core.py#L22), `MemoryOS.__init__` executes `self.db_path.parent.mkdir(parents=True, exist_ok=True)`, which can create arbitrary directories on the host filesystem under the permissions of the running process.
* **Suggested Fix:**
  Add path traversal validation inside [config.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/config.py) to check that all resolved paths remain within the project root directory:
  ```python
  def _validate_safe_path(self, path: Path) -> Path:
      resolved = path.resolve()
      if not resolved.is_relative_to(self.root_dir.resolve()):
          raise ValueError(f"Path {path} resolves outside the project root {self.root_dir}")
      return resolved
  ```

---

### Finding 2: Unused `assert_writable` Logic / Telemetry Row & DB Caps Bypassed in Write Path
* **File:Line:** [telemetry.py:16-23](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/telemetry.py#L16-L23) and [telemetry_policy.py:95-108](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/telemetry_policy.py#L95-L108)
* **Severity:** High
* **Failure/Exploit Scenario:**
  The `TelemetryPolicy` implements `assert_writable()`, which raises `TelemetryBudgetExceeded` if the database is over size/row caps. However, `assert_writable` is never called.
  Instead, the telemetry write path (`record_run` and `record_performance`) invokes `_enforce_bounds()`, which runs `self.policy.prune(conn, table)` but never throws an error or blocks the write.
  If the database file goes over the configured `max_db_mb` (due to index size, WAL file growth, or other tables like `memories`), `db_over_cap()` returns `True` permanently.
  `_enforce_bounds()` will call `prune` on every insert, but because pruning cannot shrink the database file (no `VACUUM` is run) and only prunes telemetry tables, the DB size remains over limit. The code then proceeds to write the telemetry rows anyway. This allows the telemetry database to grow unbounded.
* **Suggested Fix:**
  Enforce the bounds by invoking `assert_writable()` at the end of `_enforce_bounds()` or raising an error when hard limits cannot be resolved, preventing further database writes from running.

---

### Finding 3: Missing Database VACUUM Prevents File Size Recovery
* **File:Line:** [telemetry_policy.py:109-132](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/telemetry_policy.py#L109-L132)
* **Severity:** High
* **Failure/Exploit Scenario:**
  When `TelemetryPolicy.prune()` deletes rows using `DELETE FROM`, SQLite simply marks the database pages as free/reusable but does not release the space back to the operating system. Consequently, the physical file size (`st_size` evaluated in `db_size_mb()`) does not decrease.
  Once the database physical file size exceeds `max_db_mb`, `db_over_cap()` remains `True` permanently. This causes `_enforce_bounds()` to trigger a full pruning operation on every single telemetry write, consuming unnecessary CPU and disk write cycles without ever shrinking the file.
* **Suggested Fix:**
  Trigger a `VACUUM` command in `prune()` after deletion when the database is over capacity, or periodically run database cleanup tasks using `MemoryOS.optimize_db()`.

---

### Finding 4: Local Time vs. UTC Timezone Mismatch in Retention Pruning
* **File:Line:** [telemetry_policy.py:114-117](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/telemetry_policy.py#L114-L117) and [core.py:63](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/core.py#L63) & [123](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/core.py#L123)
* **Severity:** Medium
* **Failure/Exploit Scenario:**
  The `memory_os_telemetry` and `memory_os_performance` schemas save timestamps using local time:
  `created_at TEXT DEFAULT (datetime('now', 'localtime'))`
  However, `TelemetryPolicy.prune` queries the database using UTC cutoff strings:
  `DELETE FROM {table} WHERE created_at < datetime('now', ?)` with argument `"-{retention_days} days"`
  In SQLite, `datetime('now')` yields UTC. Comparing local time formatted strings directly against UTC cutoffs yields incorrect comparison logic:
  - If the host local time zone is UTC+3, records created exactly 30 days ago will be kept for 3 extra hours because the local timestamp string is lexicographically larger than the UTC timestamp string.
  - If the host local time zone is UTC-5 (e.g. EST), records that are only 29 days and 19 hours old (within the 30-day retention window) will be deleted prematurely.
* **Suggested Fix:**
  Standardize on UTC timestamps across both the default schema and query logic:
  `created_at TEXT DEFAULT (datetime('now'))`

---

### Finding 5: Missing Index on `created_at` in Performance Telemetry Table Causes Full Table Scans
* **File:Line:** [core.py:118-126](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/core.py#L118-L126) (affecting [telemetry_policy.py:114-117](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/telemetry_policy.py#L114-L117))
* **Severity:** Medium
* **Failure/Exploit Scenario:**
  Unlike `memory_os_telemetry`, the `memory_os_performance` table does not define an index on its `created_at` column.
  When `TelemetryPolicy.prune()` is called for `memory_os_performance` to enforce retention TTL, it executes `DELETE FROM memory_os_performance WHERE created_at < datetime('now', ?)`.
  Because there is no index, SQLite must perform a full table scan on every write under size pressure (O(N) search where N is up to 100,000 rows). Over a sequence of performance telemetry insertions, this results in O(N^2) total database operations, leading to major CPU/disk wear and performance bottlenecks.
* **Suggested Fix:**
  Add an index on `created_at` for the `memory_os_performance` table inside `core.py`:
  `CREATE INDEX IF NOT EXISTS idx_performance_created ON memory_os_performance(created_at)`

---

### Finding 6: Unhandled TOCTOU File Deletion Race in DiskGuard
* **File:Line:** [disk_guard.py:113](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/disk_guard.py#L113)
* **Severity:** Low
* **Failure/Exploit Scenario:**
  `DiskGuard._jsonl_total_mb` calculates the size of files matching `*.jsonl` by running `sum(p.stat().st_size for p in memory_dir.glob("*.jsonl"))`.
  This is a Time-of-Check to Time-of-Use (TOCTOU) race. If another thread or process (e.g. compaction or deletion routine) removes a `.jsonl` file after `glob` lists it but before `stat` is executed, the `p.stat()` call will raise a `FileNotFoundError`. Since this call is unhandled, `snapshot()` crashes completely.
* **Suggested Fix:**
  Wrap the stat call in a try-except block that returns a file size of 0 if `FileNotFoundError` occurs:
  ```python
  def _safe_stat_size(path: Path) -> int:
      try:
          return path.stat().st_size
      except FileNotFoundError:
          return 0
  ```

---

### Finding 7: Short Time-Delta Scaling Causes False Positive Growth Alerts
* **File:Line:** [disk_guard.py:146-149](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/disk_guard.py#L146-L149)
* **Severity:** Low
* **Failure/Exploit Scenario:**
  `DiskGuard` computes the growth rate between snapshots via:
  `elapsed_hours = (now - previous["timestamp"]) / 3600`
  `growth_mb_per_hour = round((tracked_mb - previous["tracked_mb"]) / elapsed_hours, 3)`
  If snapshots are run very close together (e.g., within milliseconds during concurrent operations), `elapsed_hours` is close to `0`. A minor database write (e.g. 5KB) divided by this small float is scaled up to a massive hourly growth estimate (e.g., 500 MB/hour), triggering a false positive `growth_alert`.
* **Suggested Fix:**
  Do not compute a new growth rate or update the state unless a minimum duration (e.g. 60 seconds) has elapsed since the previous snapshot timestamp.

---

### Finding 8: Telemetry Limits (Rate-limiting & Payloads) Configured but Ignored
* **File:Line:** [telemetry_policy.py:25 & 30](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/telemetry_policy.py#L25)
* **Severity:** Informational
* **Failure/Exploit Scenario:**
  The `DEFAULT_TELEMETRY_CONFIG` dictionary specifies `"raw_payloads": False` and `"max_writes_per_minute": 120`. Neither of these values is actually verified, checked, or enforced anywhere in the `telemetry.py` recording path.
* **Suggested Fix:**
  Enforce the rate limit using a sliding window or token bucket implementation in `TelemetryRecorder` to prevent write exhaustion.

---

### Finding 9: FileNotFoundError Crash when project root_dir is Missing or Unreadable
* **File:Line:** [disk_guard.py:117-118](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/disk_guard.py#L117-L118)
* **Severity:** Low
* **Failure/Exploit Scenario:**
  If the `config.root_dir` resolved path does not exist (e.g., due to an incorrect or stale `MEMORY_OS_CONFIG_PATH` env variable pointing to a missing directory), calling `shutil.disk_usage(self.config.root_dir)` raises `FileNotFoundError`. This crashes `DiskGuard.snapshot()` instead of failing gracefully.
* **Suggested Fix:**
  Wrap `shutil.disk_usage` in a try-except block and default to safe fallback values.

---

## Verdict

VERDICT: 9 issues found (3 critical/high)
