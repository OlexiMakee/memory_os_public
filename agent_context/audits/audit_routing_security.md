# Audit: routing_policy.py and security_scan.py

Scope:
- `src/memory_os/core/routing_policy.py`
- `src/memory_os/core/security_scan.py`

Focus areas reviewed:
- Secret-detection regexes for false negatives and ReDoS-prone structure.
- `data/budget_by_task.json` persistence for task-id traversal / JSON-breaking input and FIFO cap enforcement.
- `PROVIDER_REGISTRY` and routing outputs for shell execution or dynamic-import injection paths.

## Findings

### 1. Temporary AWS STS access key IDs are not detected

- Severity: medium
- File: `src/memory_os/core/security_scan.py:11`
- Code path verified: `RE_AWS_KEY` is used by `_scan_raw_line_for_secrets()` at `src/memory_os/core/security_scan.py:262-266`, and `_scan_line()` always delegates raw-line secret checks at `src/memory_os/core/security_scan.py:193-202`.
- Confirmed failure scenario: a JSONL memory row containing `AWS STS key ASIAABCDEFGHIJKLMNOP in text` produces no finding, while the sibling `AKIAABCDEFGHIJKLMNOP` on another row is reported as `aws_access_key`. This means temporary AWS credentials captured in memory/evidence/context packs can pass `memory_os security scan` silently.
- Exploit/repro:
  ```json
  {"id":"asia","summary":"AWS STS key ASIAABCDEFGHIJKLMNOP in text"}
  ```
  Running `SecurityScanner(config).scan()` against a temp `memory/nodes.jsonl` containing that row returned no finding for the `ASIA...` key.
- Suggested fix: expand the AWS access key ID regex to include STS/session prefixes, at minimum `AKIA` and `ASIA`, for example `r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"`. Keep the existing placeholder filtering and add regression tests for both prefixes.

### 2. PGP private key blocks are not detected

- Severity: medium
- File: `src/memory_os/core/security_scan.py:10`
- Code path verified: `RE_PRIVATE_KEY` is used by `_scan_raw_line_for_secrets()` at `src/memory_os/core/security_scan.py:258-260`, and redaction uses the same regex at `src/memory_os/core/security_scan.py:305-306`.
- Confirmed failure scenario: a JSONL memory row containing an ASCII-armored PGP private key header is not reported, even though the scanner flags PEM/OpenSSH-style private key headers on the same path. A leaked GPG private key in a memory summary or evidence bundle would pass the scan.
- Exploit/repro:
  ```json
  {"id":"pgp","summary":"-----BEGIN PGP PRIVATE KEY BLOCK-----\nVersion: test\nabc\n-----END PGP PRIVATE KEY BLOCK-----"}
  ```
  Running `SecurityScanner(config).scan()` against a temp `memory/nodes.jsonl` containing that row returned no finding for the PGP private key block. A sibling row containing `-----BEGIN RSA PRIVATE KEY-----` was detected as `private_key_block`.
- Suggested fix: add a second private-key header regex for PGP, for example `r"-----BEGIN PGP PRIVATE KEY BLOCK-----"`, or broaden the private-key detector to explicitly cover both PEM private-key headers and PGP private-key blocks. Add tests for PGP plus the existing RSA/OpenSSH/EC cases.

### 3. Bare GitHub API tokens in free text are not detected

- Severity: medium
- File: `src/memory_os/core/security_scan.py:12`
- Code path verified: `_scan_raw_line_for_secrets()` only checks `sk-...` tokens at `src/memory_os/core/security_scan.py:268-272`, bearer tokens at `src/memory_os/core/security_scan.py:274-279`, connection strings, and assignment-shaped secrets. A bare GitHub token in free text does not match any of those patterns.
- Confirmed failure scenario: memory/evidence text containing a pasted GitHub personal access token without a nearby `token = ...` or JSON key named `token` passes the scan. This is realistic for notes such as "paste this token ghp_..." stored in a memory summary.
- Exploit/repro:
  ```json
  {"id":"gh","summary":"paste this token ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}
  ```
  Running `SecurityScanner(config).scan()` against a temp `memory/nodes.jsonl` containing that row returned `findings_count 0`.
- Suggested fix: add explicit regexes for common GitHub token families, for example classic and fine-grained prefixes such as `ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, and `github_pat_`, with conservative length/charset checks. Redact these tokens using the same pattern in `_redact()`, and add regression tests for bare-token and assignment-token forms.

## Files With No Confirmed Issues

### `src/memory_os/core/routing_policy.py`

No confirmed issue found for the requested budget-bypass/corruption checks.

Verified details:
- `task_id` is never used to construct a filesystem path. The per-task file path is fixed in `__init__()` as `self.data_dir / "budget_by_task.json"` at `src/memory_os/core/routing_policy.py:188-190`.
- `record_task_usage()` normalizes `task_id` with `str(task_id)` and stores it only as a JSON object key at `src/memory_os/core/routing_policy.py:220-228`.
- A task id containing path traversal, quotes, a newline, brackets, and JSON-looking syntax was serialized by `json.dump()`, reloaded with `json.loads()`, and did not create another file or break the JSON object.
- The only write path found for `budget_by_task.json` is `record_task_usage()` -> `_save_task_budget()`. `grep -RIn "budget_by_task"` found no other source write path.
- The FIFO cap is enforced before every save in that write path at `src/memory_os/core/routing_policy.py:229-233`. A repro with 505 unique task IDs left exactly 500 entries.

No confirmed issue found for `PROVIDER_REGISTRY` dynamic import or shell injection.

Verified details:
- `PROVIDER_REGISTRY` is a fixed in-code dictionary at `src/memory_os/core/routing_policy.py:18-42`.
- `test_provider(name)` performs a dictionary lookup only and returns `unknown provider` for unknown names at `src/memory_os/core/routing_policy.py:248-260`; it does not import a module named by user input.
- `_adapter_installed()` calls `find_spec()` only on fixed module names embedded in `PROVIDER_REGISTRY`, not on user-provided provider/model strings, at `src/memory_os/core/routing_policy.py:11-15`.
- `route()` returns static provider/model strings from `LLMRouter.route()` and does not shell out or instantiate/import provider classes.

### `src/memory_os/core/security_scan.py`

No confirmed ReDoS issue found in the reviewed regexes.

Verified details:
- The scanner regexes use bounded character classes and simple alternation; I did not find nested quantifiers or ambiguous recursive-style constructs that would create catastrophic backtracking.
- A direct check of `_scan_raw_line_for_secrets()` against a 200,000-character assignment-style line completed in about 0.004 seconds in this environment.

## VERDICT

3 issues found (0 critical/high)
