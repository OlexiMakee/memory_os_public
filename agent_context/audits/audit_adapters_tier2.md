# Security and Correctness Code Review Report: Tier 2 Adapters

This report presents findings from an adversarial code review of the Tier 2 optional adapters in the `memory_os` codebase:
1. `src/memory_os/adapters/ollama_adapter.py`
2. `src/memory_os/adapters/markitdown_adapter.py`
3. `src/memory_os/adapters/otel_exporter.py`
4. `src/memory_os/adapters/duckdb_adapter.py`
5. `src/memory_os/adapters/litellm_adapter.py`

---

## Findings

### Finding 1: `src/memory_os/adapters/litellm_adapter.py:37`
- **Severity**: High
- **Issue**: Unhandled exception leakage due to unprotected attribute access on `decision` object in the public `complete()` method.
- **Failure Scenario / Exploit**: The `complete()` method on `LiteLLMAdapter` takes a `decision` parameter. On lines 37-39, the attributes `decision.provider`, `decision.model`, and `decision.reason` are accessed directly outside of any `try/except` block. If `decision` is passed as `None` (which can occur if upstream routing fails, is not configured, or is bypassed), the call will raise an `AttributeError` that propagates uncaught to the caller, violating the design contract that lazy-loaded optional adapters must handle all failures gracefully and return `{"ok": False, "detail": ...}` instead of raising exceptions.
- **Suggested Fix**: Move the attribute extraction logic for the `decision` object inside the `try...except Exception as exc:` block (or wrap the top-level body of the `complete()` method in a `try...except Exception:` block). Additionally, add a validation check for `decision is None` and return a clean failure status.

---

### Finding 2: `src/memory_os/adapters/otel_exporter.py:51`
- **Severity**: High
- **Issue**: Unhandled exception leakage during database instantiation and connection retrieval in the public `export()` method.
- **Failure Scenario / Exploit**: In the `export()` method on `OtelExporter`, the lines `mos = MemoryOS(self.config)` and `conn = mos.get_connection()` are executed outside the method's `try` blocks. If the target SQLite database is corrupted, locked, or inaccessible, or if folder permissions prevent creating the telemetry directory during `MemoryOS.__init__`, a `sqlite3.Error`, `sqlite3.OperationalError`, or `PermissionError` will be raised. This will escape the public method and crash the caller instead of returning a clean error dictionary.
- **Suggested Fix**: Move the `MemoryOS` instantiation and connection retrieval code inside the main `try-except` block (or wrap the entire method body in a top-level `try...except Exception:` block).

---

### Finding 3: `src/memory_os/adapters/markitdown_adapter.py:23`
- **Severity**: Medium
- **Issue**: Arbitrary File Read (Path Traversal) via unsanitized file paths passed to the public `convert()` method.
- **Failure Scenario / Exploit**: The `convert()` method accepts a `path: str` directly from the caller, checks if it is a file via `os.path.isfile(path)`, reads it via `open(path, "rb")`, and passes the path to `MarkItDown().convert(path)`. The adapter performs no directory containment or validation check. If an attacker controls the file path parameter, they can pass absolute paths or path traversal sequences (such as `../../../../etc/passwd`) to read arbitrary local files that the application process has permissions to access, receiving the contents in the returned `markdown_text` field.
- **Suggested Fix**: Limit the allowed directory scope by resolving the input path via `Path(path).resolve()` and verifying that the resolved path is inside an expected base directory (such as the workspace root directory).

---

### Finding 4: `src/memory_os/adapters/markitdown_adapter.py:30`
- **Severity**: Low
- **Issue**: Unhandled `TypeError` exception leakage due to unprotected validation checks in the public `convert()` method.
- **Failure Scenario / Exploit**: The `convert()` method performs `os.path.isfile(path)` outside of any `try/except` block. If `path` is passed with an invalid type (such as `None` or an integer), `os.path.isfile()` will raise a `TypeError`. This exception propagates out of the public method instead of being caught and returning `{"ok": False, "detail": ...}`.
- **Suggested Fix**: Wrap all logic inside the `convert()` method in a single top-level `try...except Exception:` block to guarantee that no argument validation exceptions escape.

---

### Finding 5: `src/memory_os/adapters/ollama_adapter.py`
- **Verdict**: No issues found.
- **Details**: A thorough review of `ollama_adapter.py` confirmed that the adapter handles dependencies, imports, and client calls inside appropriate `try-except` blocks. The package-level `is_available()` check also handles configuration/import exceptions safely. No unhandled exceptions can escape the public methods.

---

### Finding 6: `src/memory_os/adapters/duckdb_adapter.py`
- **Verdict**: No issues found.
- **Details**: A thorough review of `duckdb_adapter.py` confirmed that all public methods (`report()` and `export()`) are fully wrapped in `try-except Exception` blocks, ensuring that all runtime exceptions are caught and returned as structured error dicts. Target file export paths and topic arguments are validated against strict allowlists, preventing SQL injection or path traversal.

---

## Verdict
VERDICT: 4 issues found (2 critical/high)
