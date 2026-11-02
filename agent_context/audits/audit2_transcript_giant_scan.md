# Adversarial Security and Correctness Audit Report

This report presents the findings of a security and correctness review of the following two files:
1. `src/memory_os/toolkit/transcript_ingestor.py`
2. `src/memory_os/toolkit/giant_scan.py`

---

## 1. Analysis of `transcript_ingestor.py`

### Finding 1.1: Unbounded File Read / Memory Exhaustion Vulnerability (OOM Denial of Service)
* **File & Line:** [src/memory_os/toolkit/transcript_ingestor.py:53](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/transcript_ingestor.py#L53)
* **Severity:** High
* **Description:** `TranscriptIngestor.parse_transcript` reads the entire transcript file into memory via `transcript_path.read_text(encoding="utf-8")` and splits it into lines before selecting the last `max_lines`. If a huge or malicious log file is processed, it will load the entire contents into memory at once, potentially causing an Out of Memory (OOM) crash or hanging the daemon.
* **Reproduction Scenario:**
  1. Create a large 5GB `transcript.jsonl` file.
  2. Invoke `TranscriptIngestor(config).ingest(Path("transcript.jsonl"))`.
  3. The `read_text()` call loads 5GB into memory, causing the Python process to crash with an Out of Memory error.
* **Suggested Fix:** Instead of loading the entire file, read the file line-by-line to maintain a rolling buffer (e.g., using `collections.deque(maxlen=max_lines)`) or seek to the end of the file and read backwards.

### Finding 1.2: Unhandled TypeError causing Parser Crash
* **File & Line:** [src/memory_os/toolkit/transcript_ingestor.py:66-67](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/transcript_ingestor.py#L66-L67)
* **Severity:** Medium
* **Description:** The parsed conversation extraction loop attempts to check `len(content) > 1000` and slice it via `content[:1000]` to truncate long outputs. However, if `"content"` in the transcript JSON lines contains a non-string type (such as a dictionary, list, integer, or boolean), `len(content)` or `content[:1000]` will throw a `TypeError`. Since the exception handling block only catches `json.JSONDecodeError`, this TypeError will propagate and crash the ingestion process.
* **Reproduction Scenario:**
  1. Write a line to `transcript.jsonl` with an integer or dictionary content, e.g., `{"type": "status", "content": 100}` or `{"type": "data", "content": {"key": "val"}}`.
  2. Run the ingestion process.
  3. The check `len(content)` on the integer throws `TypeError: object of type 'int' has no len()`, causing the parser to fail and terminate.
* **Suggested Fix:** Check the type of `content` before applying string length checks and slicing, or coerce it to a string first:
  ```python
  content = data.get("content", "")
  if isinstance(content, str):
      if len(content) > 1000:
          content = content[:1000] + "... [TRUNCATED]"
  else:
      content = str(content)
  ```

### Analysis of Extracted Field Propagation & Downstream File Path Traversal:
* Within `transcript_ingestor.py` itself, parsed transcript content is treated strictly as data (it is serialized into JSON and written to `task_capsules.jsonl` without shelling out or evaluating f-strings/dynamic code).
* However, downstream compaction code in `compactor.py` reads these capsules and extracts fields (like `node_id`), which are then passed to `PolyglotExporter` to generate files (e.g., `_export_to_cursor`, `_export_to_antigravity`, `_export_to_claude`) using `f"{node_id}.mdc"` or `f"{node_id}.md"`. Since `node_id` is never sanitized/validated for path traversal sequences (like `..` or `/`), a poisoned transcript can lead to arbitrary file writes outside the project root when compaction runs.

---

## 2. Analysis of `giant_scan.py`

### Finding 2.1: Sibling Directory Scan Boundary Bypass (Path Prefix Vulnerability)
* **File & Line:** [src/memory_os/toolkit/giant_scan.py:223](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/giant_scan.py#L223)
* **Severity:** High
* **Description:** In `GiantScanRunner.run`, the configuration path containment check is `not str(scan_root).startswith(str(self.root))`. Because `self.root` has no trailing directory separator (e.g., `/Users/oleksii/Documents/sandbox/memory_os`), a sibling directory starting with the same prefix string (e.g., `/Users/oleksii/Documents/sandbox/memory_os_secrets`) will pass validation because `"/Users/oleksii/Documents/sandbox/memory_os_secrets".startswith("/Users/oleksii/Documents/sandbox/memory_os")` is `True`. This bypasses repository boundaries.
* **Reproduction Scenario:**
  1. Assume project root is `/Users/oleksii/Documents/sandbox/memory_os`.
  2. Create a sibling directory `/Users/oleksii/Documents/sandbox/memory_os_secrets` containing private documents.
  3. Run the scan: `memory_os giant-scan --target-dir ../memory_os_secrets`.
  4. The check resolves to `True`, and the scanner proceeds to collect and leak the files in `/Users/oleksii/Documents/sandbox/memory_os_secrets`.
* **Suggested Fix:** Verify directory containment using `Path.is_relative_to()` or check if the resolved path starts with the project root plus a trailing path separator:
  ```python
  try:
      scan_root.relative_to(self.root)
  except ValueError:
      return {"status": "aborted", "reason": "Target directory is outside project root."}
  ```

### Finding 2.2: Arbitrary File Disclosure via Symlink Following
* **File & Line:** [src/memory_os/toolkit/giant_scan.py:107-133](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/giant_scan.py#L107-L133)
* **Severity:** High
* **Description:** `RepoCollector.collect` uses `rglob("*")` and checks if `path.is_file()` is True. In Python, `is_file()` evaluates to `True` for symbolic links pointing to regular files. Since the script does not check `path.is_symlink()`, it will follow the symlink and read arbitrary files located outside the repository boundaries.
* **Reproduction Scenario:**
  1. Create a symbolic link inside the repository pointing to a sensitive file outside: `ln -s /etc/passwd src/memory_os/toolkit/test_symlink.py`.
  2. Run `memory_os giant-scan`.
  3. `RepoCollector` walks the tree, finds `test_symlink.py`, verifies it has a `.py` suffix, checks `is_file()`, reads `/etc/passwd`, and includes its full contents in the prompt sent to the LLM.
* **Suggested Fix:** Check for symlinks and skip them:
  ```python
  if path.is_symlink():
      continue
  ```

### Finding 2.3: Unbounded Scan Size leading to Out of Memory (OOM) Crash
* **File & Line:** [src/memory_os/toolkit/giant_scan.py:228-231](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/giant_scan.py#L228-L231)
* **Severity:** Medium
* **Description:** In `GiantScanRunner.run`, the safety budget check (`char_count > CHAR_BUDGET_WARNING`) is performed only *after* the collector has completely walked the directory and loaded all file contents into memory. If the scan is pointed at a directory containing thousands of source files, the program will exhaust system RAM trying to read and concatenate everything, causing a crash before checking the budget.
* **Reproduction Scenario:**
  1. Point `giant-scan` at a large directory containing thousands of files (e.g., 10,000 source files of 400KB each).
  2. The process runs `collect()` which loops through all files and reads them into memory.
  3. RAM consumption exceeds limits, crashing with OOM before reaching the budget check.
* **Suggested Fix:** Maintain a running tally of collected character count inside the file loop in `RepoCollector.collect()`. If the cumulative count exceeds a predefined hard threshold, immediately raise a limit exception or return early.

---

## 3. Scope and Shell Execution Verification
* **Shell out to external tools:** We verified by walking the imports and functions of `giant_scan.py` that it does **NOT** invoke any shell commands or external tools. All LLM calls and file operations are conducted via standard python APIs (`urllib` and `pathlib`).

---

VERDICT: 5 issues found (3 critical/high)
