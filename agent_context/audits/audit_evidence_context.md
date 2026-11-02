# Security and Correctness Audit Report

**Scope:** 
- `src/memory_os/core/context_pack.py`
- `src/memory_os/core/evidence.py`

**Focus:** Core privacy, secret redaction, and path isolation.

---

## Confirmed Vulnerabilities & Correctness Issues

### Finding 1: Contract file parsing bypasses secret redaction
- **File:Line**: [context_pack.py:326](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/context_pack.py#L326) (`_parse_contract`)
- **Severity**: High
- **Exploit/Failure Scenario**: 
  The `_parse_contract()` method reads the contract file and extracts fields (`task_summary`, `constraints`, `verification_plan`) directly. The returned contract fields are never passed through `ContextRegistry.redact()`. When `to_markdown()` is called or the pack dict is returned, any raw secrets (like `sk-...` API keys) that were inside the contract file are leaked completely unredacted.
- **Suggested Fix**: 
  Apply `ContextRegistry.redact()` to the extracted `task_summary`, `constraints`, and `verification_plan` fields before returning them from `_parse_contract()`.

---

### Finding 2: Path traversal in contract file loading
- **File:Line**: [context_pack.py:338](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/context_pack.py#L338) (`_parse_contract`)
- **Severity**: High
- **Exploit/Failure Scenario**: 
  `_parse_contract()` accepts an arbitrary `contract_path` without checking if it is inside the project root directory or restricting directory traversal. An attacker or user can supply `contract_path="/etc/passwd"` or `../../some_file`. If the file does not contain a `#` header, the entire file content is assigned to `task_summary` and printed completely unredacted in `to_markdown()` / returned in the pack.
- **Suggested Fix**: 
  Validate that the resolved `contract_path` is strictly within `config.root_dir` (e.g., check `path.resolve().relative_to(config.root_dir)`).

---

### Finding 3: Path traversal in snapshot builder via file path matching
- **File:Line**: [context_pack.py:69](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/context_pack.py#L69) (`build` calling `ContextRegistry.build_snapshot`)
- **Severity**: High
- **Exploit/Failure Scenario**: 
  `ContextPackBuilder.build()` calls `ContextRegistry.build_snapshot(paths=paths)`. `iter_files()` in `ContextRegistry` resolves the candidate paths relative to the root directory using `(self.root_dir / item).resolve()`. If `paths` contains `../` or absolute paths, it escapes the root directory. If a file is matched by a task keyword, it is included in `relevant_files` along with its full raw content, allowing arbitrary local file disclosure of any file outside the workspace root (e.g. `paths=["../dummy_outside.txt"]` with task="dummy").
- **Suggested Fix**: 
  Ensure all candidate paths in `iter_files()` are validated to be strictly within `self.root_dir` (e.g., check `base.resolve().relative_to(self.root_dir)`).

---

### Finding 4: Flawed secret redaction regexes in ContextRegistry
- **File:Line**: [context.py:27](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/modules/context.py#L27) (`ContextRegistry.redact`)
- **Severity**: Medium
- **Exploit/Failure Scenario**: 
  The secret redaction regexes have critical bypasses:
  1. The pattern for matching key-value secrets (`(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^\s'\"',}]+`) stops at the first space or quote. If a secret contains spaces or quotes (e.g. `api_key = "super secret value"`), only the first token is redacted, leaking the rest (e.g. `[REDACTED] secret value"`).
  2. It misses secrets assigned to common variable names not explicitly in the whitelist keyword group (e.g. `stripe_key` or `github_pat` are not redacted).
- **Suggested Fix**: 
  Update the regex to capture quote-delimited multi-word strings fully, and expand the keyword matches.

---

### Finding 5: Path traversal via `task_id` in EvidenceStore
- **File:Line**: [evidence.py:43](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/evidence.py#L43) (`bundle_path`)
- **Severity**: High
- **Exploit/Failure Scenario**: 
  `bundle_path` constructs paths as `self.evidence_dir / task_id / "bundle.json"` without validating `task_id`. A caller or CLI user can supply a `task_id` containing `../` (e.g., `../../outside_task`), which resolves outside `evidence_dir` and allows reading/writing `bundle.json` files arbitrarily on the system.
- **Suggested Fix**: 
  Validate `task_id` against a safe regex (e.g., `^[a-zA-Z0-9_-]+$`) or ensure that the resolved bundle path is strictly within `self.evidence_dir`.

---

### Finding 6: Predictable/world-readable file permissions for evidence bundles
- **File:Line**: [evidence.py:53](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/evidence.py#L53) (`_save`)
- **Severity**: Low
- **Exploit/Failure Scenario**: 
  In `_save()`, directories are created using `mkdir(parents=True, exist_ok=True)` and files are written using `write_text()`. No file permission restriction is specified. On multi-user systems, these files are written with default permissions (typically `0o644`), making command output summaries, exit codes, and changed file paths visible to other users.
- **Suggested Fix**: 
  Apply owner-only permissions (e.g. `0o600` for the file and `0o700` for parent directories) when writing evidence bundles.

---

### Finding 7: Unredacted Memory Nodes in Context Pack
- **File:Line**: [context_pack.py:201](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/core/context_pack.py#L201) (`build`)
- **Severity**: Medium
- **Exploit/Failure Scenario**: 
  In `build()`, memory nodes are retrieved via `MemorySearcher` and copied directly into the pack without calling `ContextRegistry.redact()` on their text fields (such as `summary` or `tags`). If these nodes in the memory graph database contain secrets, they leak raw into the context pack.
- **Suggested Fix**: 
  Iterate over memory nodes and redact their text fields before adding them to `relevant_memory_nodes`.

---

## Verified Safe Behaviors

### 1. Truncation Order
In `_bound_and_redact()` in `evidence.py:29`, `ContextRegistry.redact()` is executed before checking the length of the string and truncating. This ensures that no secrets are cut in half and leaked as visible halves during the truncation process.

### 2. Command Execution Safety
In `add_command()` in `evidence.py:94`, the command is executed using `subprocess.run(list(command), ...)` without setting `shell=True`. This prevents command injection vulnerabilities via caller-supplied argument vectors.

---

VERDICT: 7 issues found (4 critical/high)
