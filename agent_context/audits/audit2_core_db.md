# Audit 2: Core DB and Queue

Scope reviewed:
- `src/memory_os/core/core.py`
- `src/memory_os/core/queue.py`
- Supporting verification: `src/memory_os/core/config.py`, `src/memory_os/core/interfaces.py`, queue/core callers found under `src/memory_os`, and targeted temp-DB repros.

Constraints followed:
- No source files under `src/` or `scripts/` were edited.
- No git write commands were run.
- Only this Markdown report was created.

## Finding 1: `MemoryOS(db_path=...)` bypasses `MemoryOSConfig.db_path` confinement

- File: `src/memory_os/core/core.py:17`
- Severity: high

`MemoryOS.__init__` uses the confined `config.db_path` only when the explicit `db_path` argument is omitted. If any caller supplies `db_path`, line 20 stores `Path(db_path)` directly, then line 22 creates the parent directory and line 23 initializes the SQLite database there. That bypasses the `confine_to_root` protection in `MemoryOSConfig.db_path`.

Concrete repro verified in a temp directory:

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from memory_os.core.config import MemoryOSConfig
from memory_os.core.core import MemoryOS

with TemporaryDirectory(dir="/private/tmp") as td:
    root = Path(td) / "root"
    root.mkdir()
    config_path = root / "memory_os.config.json"
    config_path.write_text('{"db_path":"memory/memory_os.db"}', encoding="utf-8")
    outside_db = Path(td) / "outside" / "escaped.db"

    config = MemoryOSConfig(config_path=str(config_path))
    MemoryOS(config=config, db_path=str(outside_db))

    assert outside_db.exists()
    assert not str(outside_db).startswith(str(root))
```

This creates `/private/tmp/.../outside/escaped.db` even though the config root is `/private/tmp/.../root`. Existing in-repo callers I found use `MemoryOS(config)` rather than `MemoryOS(..., db_path=...)`, so I did not find a current CLI/daemon path exposing this directly. The constructor is still a public API and currently reintroduces the same class of path escape that `MemoryOSConfig.db_path` rejects.

Suggested fix:
- Prefer removing the `db_path` override from `MemoryOS.__init__` and requiring callers to pass a config.
- If the override must remain for tests or adapters, validate it with the same confinement rule before creating directories, e.g. resolve it through `confine_to_root(db_path, config.root_dir)`.
- Add a regression test parallel to `test_config_path_confinement_and_redaction` proving `MemoryOS(config, db_path="../escape.db")` and an absolute outside-root path are rejected.

## Finding 2: `TaskQueue` cannot enqueue or dequeue because `memory_os_jobs` is never created

- File: `src/memory_os/core/queue.py:16`
- Severity: medium

`TaskQueue.enqueue`, `TaskQueue.dequeue`, and `TaskQueue.complete` all operate on `memory_os_jobs`, but `MemoryOS.init_db()` in `src/memory_os/core/core.py` creates telemetry, memories, FTS, performance, graph node, and graph edge tables only. I found no `CREATE TABLE ... memory_os_jobs` elsewhere in the repo.

Concrete repro verified against a fresh temp DB:

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from memory_os.core.core import MemoryOS
from memory_os.core.queue import TaskQueue

with TemporaryDirectory() as td:
    db = MemoryOS(db_path=str(Path(td) / "memory_os.db"))
    TaskQueue(db).enqueue("task", "provider", "model", "input")
```

Actual failure:

```text
OperationalError: no such table: memory_os_jobs
```

A daemon or CLI path that starts using `TaskQueue` will fail on first enqueue/dequeue against a database initialized by the main `MemoryOS` class.

Suggested fix:
- Add `memory_os_jobs` schema creation to `MemoryOS.init_db()`, including the columns used by `queue.py`: `job_id`, `task_type`, `priority`, `provider`, `model`, `input_ref`, `status`, and `created_at`.
- Set `status TEXT NOT NULL DEFAULT 'queued'`.
- Add an index matching dequeue order and filter, for example `(status, priority DESC, created_at ASC)`.
- Add a temp-DB regression test that initializes `MemoryOS`, enqueues one task, dequeues it, verifies it is marked `processing`, then completes it.

## Confirmed Non-Issues

### SQL injection

No confirmed SQL injection was found in `core.py` or `queue.py`.

`core.py` uses parameterized placeholders for caller-controlled values in memory insertion, memory retrieval limit, FTS query text, graph node fields, and graph edge fields. `queue.py` parameterizes all caller-supplied task fields and job IDs.

The only dynamic SQL identifier construction in scope is:

```python
for table in ("memories_fts", "graph_nodes_fts"):
    conn.execute(f"INSERT INTO {table}({table}) VALUES('optimize')")
```

Those table names are fixed literals defined inside `core.py`, not caller-supplied input, so I do not classify this as SQL injection.

### Connection handling

No confirmed connection leak was found in `core.py` or `queue.py`. Every `sqlite3.Connection` opened by `MemoryOS.get_connection()` in these files is closed in a `finally` block on the inspected paths, including exception paths. `TaskQueue.dequeue()` also rolls back before re-raising exceptions.

### Unsafe SQLite pragmas/extensions

No unsafe SQLite pragma or extension setting was found in the scoped files. The scoped code enables `PRAGMA foreign_keys = ON` and runs `wal_checkpoint(TRUNCATE)` during optimization. I found no `enable_load_extension`, `load_extension`, or `ATTACH` usage in the scoped files.

### Queue race under concurrent dequeue

No duplicate-dequeue race was confirmed in `TaskQueue.dequeue()`. It starts `BEGIN IMMEDIATE` before selecting the highest-priority queued row and updates that row to `processing` before commit, so concurrent dequeuers serialize around the select/update section.

I also could not confirm the prompt's daemon/CLI shared-queue scenario in the current tree: searching current `src/memory_os` and `scripts` found no daemon or CLI caller of `TaskQueue`, `enqueue`, or `dequeue`. The queue is currently broken earlier because the jobs table is absent.

VERDICT: 2 issues found (1 critical/high)
