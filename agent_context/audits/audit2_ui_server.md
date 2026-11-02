# Security and Correctness Code Audit Report: Memory OS UI Server

This report documents the security and correctness findings from an adversarial code audit of the hand-rolled local UI server (`src/memory_os/ui/server.py` and its dependencies under `src/memory_os/ui/data_provider.py`). 

---

## Findings

### Finding 1: Path Traversal/Arbitrary File Read inside Project Root via `/api/read_file`
- **Location**: [server.py:90-112](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/ui/server.py#L90-L112), calling [data_provider.py:99-114](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/ui/data_provider.py#L99-L114)
- **Severity**: **Critical**
- **Exploit Scenario**:
  An attacker or a malicious script running on an external website (exploiting the CORS bypass described in Finding 3) makes a GET request to:
  `http://localhost:8080/api/read_file?path=.env`
  The server resolves `.env` to the project root `.env` file, checks that the resolved absolute path starts with the project root string, and immediately returns the file content. This leaks all LLM provider API keys and other secrets stored in `.env`.
- **Suggested Fix**:
  Restrict file access to a whitelisted subdirectory (e.g., `evidence/`) or implement a strict path resolution block that explicitly rejects sensitive files such as `.env`, `.git` directory files, configuration files, and database files (`.db`).

---

### Finding 2: Path Traversal / Sibling Directory Bypass in `_resolve_file_path`
- **Location**: [data_provider.py:84-86](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/ui/data_provider.py#L84-L86)
- **Severity**: **High**
- **Exploit Scenario**:
  The directory prefix verification is implemented using plain string prefix matching:
  `str(target_path).startswith(str(project_root))`
  If the project root is located at `/Users/oleksii/Documents/sandbox/memory_os` and a sibling directory named `/Users/oleksii/Documents/sandbox/memory_os_secrets` exists on the system, the string prefix check succeeds. An attacker can request:
  `http://localhost:8080/api/read_file?path=../memory_os_secrets/credentials.txt`
  This resolves to `/Users/oleksii/Documents/sandbox/memory_os_secrets/credentials.txt`. Because this path starts with the prefix `/Users/oleksii/Documents/sandbox/memory_os`, the server serves the file, bypassing the containment.
- **Suggested Fix**:
  Use `confine_to_root` from `memory_os.core.safe_id` or call `.relative_to()` to ensure path containment is checked using proper path components rather than raw string prefixes.

---

### Finding 3: Missing CORS Access Restrictions / Origin Verification
- **Location**: [server.py:22-29](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/ui/server.py#L22-L29)
- **Severity**: **Critical**
- **Exploit Scenario**:
  The handler sends `Access-Control-Allow-Origin: *` on all responses and performs no validation of the `Origin` or `Referer` headers. A user running the visualizer locally visits a malicious website (e.g., `http://attacker.com`). A script on that website makes fetch requests to `http://localhost:8080/api/graph` and `http://localhost:8080/api/read_file?path=.env`. The browser permits the cross-origin responses because of the wildcard CORS header, allowing the attacker to exfiltrate the user's entire memory graph and private API keys.
- **Suggested Fix**:
  Remove `Access-Control-Allow-Origin: *`. If cross-origin sharing is required for local visualizer development, strictly validate that incoming `Origin` and `Referer` headers match the expected localhost address and port, or require a dynamically generated random token in the URL on startup.

---

### Finding 4: Unvalidated Space Path Traversal and Safe ID Bypass in `/api/switch_space`
- **Location**: [server.py:171-188](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/ui/server.py#L171-L188)
- **Severity**: **High**
- **Exploit Scenario**:
  The `/api/switch_space` POST handler receives a `space` parameter and assigns it directly to `self.server.provider.config.space = new_space` without sanitization or calling `validate_safe_id`. This directly bypasses the `validate_safe_id` validation implemented in the configuration constructor.
  If an attacker sends a POST request with `{"space": "../../some_other_directory"}` where a `nodes.jsonl` exists, the configuration space updates to the relative path. Subsequent repository read and write requests will target paths outside the project root.
- **Suggested Fix**:
  Sanitize the user-controlled `new_space` variable using `validate_safe_id` in the server POST handler, or implement a property setter on the configuration object that enforces safe ID validations.

---

### Finding 5: Denial of Service (DoS) via Unbounded POST Request Body Reads
- **Location**: [server.py:172-174](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/ui/server.py#L172-L174), [server.py:214-216](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/ui/server.py#L214-L216), [server.py:237-239](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/ui/server.py#L237-L239), [server.py:261-263](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/ui/server.py#L261-L263), [server.py:316-317](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/ui/server.py#L316-L317)
- **Severity**: **Medium**
- **Exploit Scenario**:
  The server reads user-supplied request bodies using `self.rfile.read(content_length)` where `content_length` is derived directly from the request headers without an upper size bound. A client sends a POST request to `/api/nodes/verify` with a `Content-Length` header set to `1000000000` (1 GB). The Python server allocates 1 GB of memory attempting to read the payload, exhausting system memory and triggering an Out of Memory (OOM) crash.
- **Suggested Fix**:
  Enforce a maximum limit on the `Content-Length` header (e.g. 5 MB or 10 MB) in the HTTP server handler and return a `413 Payload Too Large` error if exceeded.

---

### Finding 6: Unbounded File Read in `read_evidence_file` (DoS)
- **Location**: [data_provider.py:111-112](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/ui/data_provider.py#L111-L112)
- **Severity**: **Low**
- **Exploit Scenario**:
  The `read_evidence_file` function reads the target file completely into memory via `f.read()`. If the project contains a large file (e.g., a database file, dataset, or zip file of several hundred megabytes), requesting it via `/api/read_file` loads the entire file into memory at once, risking process termination due to OOM.
- **Suggested Fix**:
  Validate the file size using `os.path.getsize` before opening it, and reject files exceeding a reasonable threshold (e.g., 10 MB), or stream the file in smaller chunks.

---

### Finding 7: Unvalidated Command Argument Injection in `/api/link-infer`
- **Location**: [server.py:315-331](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/ui/server.py#L315-L331)
- **Severity**: **Low**
- **Exploit Scenario**:
  The server invokes an external command via `subprocess.run` passing the `method` and `resource_mode` strings directly from the request payload to the command arguments. Although shell execution is disabled (as the command is passed as a list of strings rather than a raw shell string), unvalidated parameter strings can lead to argument injection. For example, a request payload containing `{"method": "--help"}` will inject the `--help` flag, altering the expected CLI command flow and causing it to dump CLI usage information.
- **Suggested Fix**:
  Validate `method` and `resource_mode` against a strict whitelist of accepted options (e.g., `["cascade", "simple"]`) before invoking `subprocess.run`.

---

## Verdict

VERDICT: 7 issues found (4 critical/high)
