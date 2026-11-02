# Security & Correctness Audit Report: Orchestrator, Workflow Manager, Scheduler

Scope requested:
- `src/memory_os/core/orchestrator.py`
- `src/memory_os/core/workflow_manager.py`
- `src/memory_os/core/scheduler.py`

Additional path audited to satisfy the interval-scheduling focus:
- `src/memory_os/core/daemon.py`, because `test_auto.py:14` imports `ScheduleEngine` from `memory_os.core.daemon`, not from `memory_os.core.scheduler`.

## Scope Assessment Against Focus Areas

- **(a) Huge interval value overflow / infinite loop / busy-spin:** No issue found for huge numeric intervals in the actual interval scheduler. A focused reproduction with `10**100` and `float("inf")` did not overflow, loop, or busy-spin; the task simply did not run. However, malformed non-numeric interval values are not validated and can crash the daemon scheduler before task-level exception handling applies. See Finding 1.
- **(b) Dynamic dispatch by caller-supplied string name:** No confirmed dynamic-dispatch-injection issue found in `orchestrator.py` or `workflow_manager.py`. There is no `getattr(module, user_string)`, `eval`, `exec`, `globals()`, `locals()`, `importlib` dispatch, or dictionary of caller-supplied string names used to invoke callbacks in the scoped files. `WorkflowManager` calls fixed interface methods on registered module objects.
- **(c) Exception in one scheduled/orchestrated task crashing the loop:** The daemon `ScheduleEngine` catches exceptions thrown inside task callbacks, matching the existing `test_auto.py` coverage. That protection does not cover scheduler metadata errors before the callback invocation. Separately, `HardwareScheduler.execute_parallel()` in scoped `scheduler.py` propagates one worker exception and aborts the aggregate parallel job instead of returning/logging a per-task failure result. See Findings 1 and 2.

## Detailed Findings

### Finding 1: malformed scheduled-task interval can crash the daemon loop before callback exception handling

- **File:Line:** `src/memory_os/core/daemon.py:131` (required focus path; `test_auto.py:14` imports this scheduler from `daemon.py`)
- **Severity:** Medium
- **Concrete Failure Scenario:** `ScheduleEngine.add_task()` stores `interval_seconds` without validating type or bounds at `daemon.py:120-126`. `run_pending()` then evaluates `now - task["last_run"] >= task["interval"]` at `daemon.py:131` before entering the `try` block that catches callback failures at `daemon.py:132-138`.

  A plugin, integration, or internal caller that registers a task with a malformed interval such as `"0"` can stop the daemon scheduler:

  ```python
  import logging
  from memory_os.core.daemon import ScheduleEngine

  engine = ScheduleEngine()
  engine.add_task("bad_interval", "0", lambda: None)
  engine.run_pending(logging.getLogger("audit"))
  ```

  Reproduced result:

  ```text
  TypeError: '>=' not supported between instances of 'float' and 'str'
  ```

  In `MemoryDaemon.run()`, `self.scheduler.run_pending(self.logger)` is inside the outer daemon `try` at `daemon.py:448-457`; that outer handler logs a daemon crash, sends a critical alert, then exits into `finally`, sets `is_running = False`, and stops the daemon. This is not covered by the existing "Task errors are caught gracefully" test because that test only raises from inside `task["func"]()` after the interval comparison has already succeeded.

- **Suggested Fix:** Validate interval metadata in `ScheduleEngine.add_task()` and keep scheduler bookkeeping inside a per-task guard:

  ```python
  import math

  def add_task(self, name: str, interval_seconds: float, func):
      if not isinstance(interval_seconds, (int, float)) or not math.isfinite(interval_seconds):
          raise ValueError("interval_seconds must be a finite number")
      if interval_seconds < 0:
          raise ValueError("interval_seconds must be non-negative")
      self.tasks.append({...})
  ```

  Also wrap the interval comparison and `last_run` parsing in `run_pending()` so a single corrupt task record can be logged and skipped without terminating the daemon loop.

### Finding 2: one `HardwareScheduler` worker exception aborts the whole parallel job

- **File:Line:** `src/memory_os/core/scheduler.py:29`, called by `src/memory_os/modules/compactor.py:298`
- **Severity:** Medium
- **Concrete Failure Scenario:** `HardwareScheduler.execute_parallel()` iterates `executor.map(func, items)` and appends each result. If any item callback raises an exception, `executor.map` re-raises that exception at `scheduler.py:29` and the method exits without returning partial results or per-item error records.

  Minimal reproduction against the scoped scheduler:

  ```python
  from memory_os.core.scheduler import HardwareScheduler

  def worker(x):
      if x == 2:
          raise RuntimeError("boom")
      return x * 10

  HardwareScheduler().execute_parallel(worker, [1, 2, 3], max_workers=2)
  ```

  Reproduced result:

  ```text
  RuntimeError: boom
  ```

  The real caller is `MemoryCompactor.compact_capsules()` at `compactor.py:297-299`. `_process_single_batch()` handles LLM-call and JSON-decode errors, but not every possible batch error after JSON parsing. For example, an LLM response like `{"nodes": ["bad"], "edges": []}` reaches `_panel_vote()` at `compactor.py:240`, where `_panel_vote()` expects every node to be a dict with an `"id"` key at `compactor.py:172`. That raises before `_process_single_batch()` can return its normal `{"error": ...}` shape. Because `HardwareScheduler.execute_parallel()` re-raises, one malformed batch aborts the whole compaction run and discards any successful batch results that were already computed. If triggered by daemon auto-compaction, `MemoryDaemon.auto_compact()` catches and logs the failure at `daemon.py:406-407`, so the daemon loop survives, but the scheduled compaction task fails as a unit.

- **Suggested Fix:** Make `execute_parallel()` collect per-item failures instead of propagating the first worker exception, or add a separate safe API for task-style parallel execution. For example, use `executor.submit()` plus `as_completed()` and return structured entries such as:

  ```python
  {"ok": False, "item": item, "error": str(exc)}
  ```

  Then update `MemoryCompactor.compact_capsules()` to handle those entries the same way it already handles batch-level `"error"` values. Alternatively, wrap the entire body of `_process_single_batch()` in a broad catch and return the existing error shape, but the generic scheduler should still document whether it is fail-fast or fault-isolating.

## Files With No Confirmed Issues

### `src/memory_os/core/orchestrator.py`

No confirmed issue found. `TaskOrchestrator.decompose_task()` does not execute a callback or handler selected by a caller-supplied string. The current LLM execution path is commented out (`orchestrator.py:39-40`), and the live path returns deterministic `SubTask` objects through `_mock_decomposition()`.

### `src/memory_os/core/workflow_manager.py`

No confirmed dynamic-dispatch-injection issue found. `WorkflowManager.resolve_workflow()` iterates registered module objects and calls fixed interface methods (`get_supported_levels()` and `get_workflow_profile(level)`) at `workflow_manager.py:23-27`; it does not look up methods by caller-supplied string name.

### `src/memory_os/core/scheduler.py`

No interval-based scheduling logic exists in this file. It implements `HardwareScheduler`, a parallel execution/cache helper. The confirmed issue in this file is Finding 2.

## Verification Notes

- Read the scoped files and the called interfaces: `orchestrator.py`, `workflow_manager.py`, `scheduler.py`, `module_interface.py`, and `interfaces.py`.
- Read the actual interval scheduler and daemon loop in `daemon.py` because `test_auto.py:test_schedule_engine` imports `ScheduleEngine` from that file.
- Searched for relevant dynamic dispatch primitives and call sites: `getattr`, `globals`, `locals`, `importlib`, `eval`, `exec`, `ScheduleEngine`, `HardwareScheduler`, `execute_parallel`, `WorkflowManager`, and `TaskOrchestrator`.
- Ran focused reproductions for malformed interval, huge numeric interval, and parallel worker exception behavior. No source files under `src/` or `scripts/` were modified.

VERDICT: 2 issues found (0 critical/high)
