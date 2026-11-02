# Security & Correctness Audit Report: External Sync Integrations

This report details the findings from an adversarial security and correctness audit of the following Memory OS integration modules:
- [notion_sync.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/notion_sync.py)
- [gdrive_sync.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/gdrive_sync.py)
- [linear_sync.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/linear_sync.py)

---

## Scope Assessment Against Focus Areas

* **(a) Key/Token storage/leakage on disk:** No instances were found where credentials (API keys, OAuth tokens) are written to disk in plaintext (e.g. as caches or logs) by the sync modules themselves. They reside exclusively in memory.
* **(b) Key/Token inclusion in command strings/logs/exceptions:** The integration modules themselves do not write keys to logs or exceptions. However, the custom pipeline execution wrapper leaks Google Drive tokens in stdout/logs due to incomplete regex masking.
* **(c) Path traversal / untrusted instruction execution from API response:** API response content (titles, text, IDs) is sanitized when generating node IDs, preventing path traversal. External content is not parsed or executed as instructions during the ingestion/writing phase.
* **(d) HTTP Client timeouts:** **None** of the external API calls specify a timeout on `urllib.request.urlopen`, leaving the client susceptible to blocking indefinitely.
* **(e) Unbounded pagination / file size download limit:** Both Notion/GDrive metadata fetching is unbounded in memory. Additionally, `gdrive_sync.py` downloads text/json files of arbitrary size into memory at once, risking OOM crashes. `linear_sync.py` has no pagination support for issue retrieval, causing duplicate task creation.

---

## Detailed Findings

### Finding 1: `notion_sync.py:309` & `notion_sync.py:354` - Undefined Function `fetch_page_content` causing runtime crash
* **File:Line**: [notion_sync.py:309](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/notion_sync.py#L309) & [notion_sync.py:354](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/notion_sync.py#L354)
* **Severity**: High
* **Concrete Failure Scenario**: Attempting to run `memory_os notion-sync` executes the extraction logic which contains the lines:
  ```python
  page_content = fetch_page_content(self.api_key, page_id)
  ```
  Because `fetch_page_content` is neither imported nor defined anywhere within [notion_sync.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/notion_sync.py), Python raises a `NameError: name 'fetch_page_content' is not defined` and the script immediately crashes, rendering the Notion sync command completely non-functional.
* **Suggested Fix**: Define the missing helper function in [notion_sync.py](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/notion_sync.py) to wrap `get_page_content_markdown_recursive`:
  ```python
  def fetch_page_content(api_key: str, page_id: str) -> str:
      return get_page_content_markdown_recursive(api_key, page_id)
  ```

---

### Finding 2: Lack of HTTP Timeout in all integration modules
* **File:Line**:
  - [notion_sync.py:200](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/notion_sync.py#L200)
  - [notion_sync.py:231](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/notion_sync.py#L231)
  - [notion_sync.py:261](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/notion_sync.py#L261)
  - [gdrive_sync.py:35](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/gdrive_sync.py#L35)
  - [gdrive_sync.py:56](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/gdrive_sync.py#L56)
  - [linear_sync.py:77](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/linear_sync.py#L77)
* **Severity**: Medium
* **Concrete Failure Scenario**: All three integration modules issue network requests using `urllib.request.urlopen(req)` without specifying the `timeout` parameter. If the Notion, Google Drive, or Linear APIs hang, experience socket level freezing, or drop packets, the synchronization process will block indefinitely. This freezes the CLI command or daemon thread, starving other resources and preventing future task runs.
* **Suggested Fix**: Add a standard connection/read timeout (e.g. 30 seconds) to all `urlopen` invocations:
  ```python
  with urllib.request.urlopen(req, timeout=30) as response:
  ```

---

### Finding 3: `gdrive_sync.py:57` - Unbounded file download size leading to potential memory exhaustion (OOM)
* **File:Line**: [gdrive_sync.py:57](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/gdrive_sync.py#L57) (inside `download_gdrive_file_content`)
* **Severity**: High
* **Concrete Failure Scenario**: The Google Drive sync process downloads files that do not match the media mime-types filter. If a collaborator or an external attacker places a very large non-media file (e.g., a 2GB raw SQL database dump, dataset, or log file) inside the synced Drive folder, `content_bytes = response.read()` will try to load the entire 2GB file into memory. Since strings are memory-expensive in Python, decodes and allocations will quickly exceed the process heap limit, triggering an Out of Memory (OOM) crash and terminating the daemon.
* **Suggested Fix**: Limit the maximum download size (e.g., to 10MB) by checking the `Content-Length` header before downloading, or by using a chunked reader:
  ```python
  content_length = response.getheader("Content-Length")
  if content_length and int(content_length) > 10 * 1024 * 1024:
      logger.warning(f"File {file_id} exceeds size limit. Skipping download.")
      return "[File size exceeds sync limit]"
  ```

---

### Finding 4: `linear_sync.py:43` - Lack of Pagination in Issue Queries leading to duplicate issue creation
* **File:Line**: [linear_sync.py:43](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/linear_sync.py#L43) (inside `get_linear_issues`)
* **Severity**: Medium
* **Concrete Failure Scenario**: The GraphQL query in `get_linear_issues` requests team issues without specifying cursor-based pagination. Because Linear pages responses to a maximum of 100/250 issues by default, issues beyond the first page are omitted from the returned dict `existing_issues`. When `sync_roadmap_with_linear` matches local tasks in `GLOBAL_ROADMAP.md` against `existing_issues`, any existing task whose corresponding issue lives on page 2+ of the Linear workspace will not be found, triggering the `create_linear_issue` step and creating duplicate issues in Linear on every run.
* **Suggested Fix**: Refactor `get_linear_issues` to loop and retrieve all issues using standard GraphQL connection pagination (`pageInfo { hasNextPage endCursor }`):
  ```python
  def get_linear_issues(api_key: str) -> dict:
      issues = []
      has_next = True
      cursor = None
      while has_next:
          query = """
          query($cursor: String) {
            issues(after: $cursor) {
              nodes {
                id
                title
                state { type }
              }
              pageInfo {
                hasNextPage
                endCursor
              }
            }
          }
          """
          variables = {"cursor": cursor} if cursor else {}
          data = execute_graphql(api_key, query, variables)
          issues_data = data.get("data", {}).get("issues", {})
          issues.extend(issues_data.get("nodes", []))
          page_info = issues_data.get("pageInfo", {})
          has_next = page_info.get("hasNextPage", False)
          cursor = page_info.get("endCursor")
      return {issue["title"].strip(): issue for issue in issues}
  ```

---

### Finding 5: `pipeline.py:36` - Incomplete Secret Redaction (Google Drive token leaks in logs)
* **File:Line**: [pipeline.py:36](file:///Users/oleksii/Documents/sandbox/memory_os/src/memory_os/toolkit/pipeline.py#L36) (inside `_redact_for_display`)
* **Severity**: Medium
* **Concrete Failure Scenario**: Users can run custom pipelines using CLI commands, for example: `memory_os pipeline custom "gdrive-sync --token ya29.oauth_token_here --folder-id FOLDER"`. When `_run_step` prints the executed step to stdout/logs for auditing, it calls `_redact_for_display`. However, the regex `re.sub(r"(--api-key\s+)\S+", r"\1[REDACTED]", cmd)` only flags `--api-key`. It does not match `--token`, printing the sensitive Google Drive OAuth token in plaintext to logs or standard output.
* **Suggested Fix**: Update `_redact_for_display` to strip out `--token` arguments alongside `--api-key`:
  ```python
  def _redact_for_display(cmd: str) -> str:
      """Mask secret-bearing flag values (e.g. --api-key, --token) before printing."""
      cmd = re.sub(r"(--api-key\s+)\S+", r"\1[REDACTED]", cmd)
      cmd = re.sub(r"(--token\s+)\S+", r"\1[REDACTED]", cmd)
      return cmd
  ```

---

VERDICT: 5 issues found (2 high)
