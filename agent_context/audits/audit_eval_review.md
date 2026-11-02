# Audit: eval runner/export and review-pack filename handling

Scope:
- `src/memory_os/toolkit/eval_runner.py`
- `src/memory_os/toolkit/eval_export.py`
- `src/memory_os/toolkit/review_pack.py`

Assumptions:
- Treat CLI arguments and direct Python callers as caller-controlled input.
- Source files under `src/` were reviewed read-only.
- Temporary repro files/repos were created under `/private/tmp` only.

## Findings

### 1. Export destination can escape `agent_context/eval_exports`

- Severity: high
- File: `src/memory_os/toolkit/eval_export.py:36`
- Called path: `src/memory_os/toolkit/eval_export.py:44-49`

`write_export()` builds the destination directly from caller input:

```python
destination = Path(out_path) if out_path else DEFAULT_EXPORTS_DIR / f"{suite_name}.{target}.json"
```

There are two confirmed escape paths:

1. Any direct caller that passes `out_path` can overwrite any path writable by the process, because `Path(out_path)` is accepted without checking that it resolves under the intended export directory.
2. Even with `out_path=None`, an absolute `suite_name` makes `DEFAULT_EXPORTS_DIR / f"{suite_name}.{target}.json"` resolve to the absolute path, outside `agent_context/eval_exports`. `_suite_dir()` also accepts the same absolute suite name, so the export succeeds if that outside directory contains `config.json` and `cases.jsonl`.

Concrete repro verified:

```bash
mkdir -p /private/tmp/memory_os_audit_suite_abs
printf '{"kind":"llm_judge","description":"audit"}\n' > /private/tmp/memory_os_audit_suite_abs/config.json
printf '{"id":"case1","query":"q","expected_node_id_substring":"x"}\n' > /private/tmp/memory_os_audit_suite_abs/cases.jsonl

PYTHONPATH=src python3 - <<'PY'
from pathlib import Path
from memory_os.toolkit.eval_export import write_export
p = write_export('/private/tmp/memory_os_audit_suite_abs', 'inspect')
print(p)
print(Path('/private/tmp/memory_os_audit_suite_abs.inspect.json').exists())
PY
```

Observed result:

```text
/private/tmp/memory_os_audit_suite_abs.inspect.json
True
```

Concrete failure scenario:
An automation layer exposes `write_export(..., out_path=caller_value)` or passes through a suite name from a request. A caller supplies `out_path="README.md"` or an absolute suite name such as `/private/tmp/suite`, and the process overwrites a file outside the intended export directory with generated JSON.

Suggested fix:
- Validate `suite_name` as a simple slug, for example `^[A-Za-z0-9._-]+$`, before using it in either suite lookup or output naming.
- Resolve the destination and require it to stay under a resolved export root:

```python
export_root = DEFAULT_EXPORTS_DIR.resolve()
destination = (export_root / f"{suite_name}.{target}.json").resolve()
destination.relative_to(export_root)
```

- If arbitrary `out_path` is intentionally supported, require an explicit unsafe mode or document it as a privileged API, then still reject directories outside a caller-provided allowed root by default.

### 2. Eval suite names can traverse outside `toolkit/evals`

- Severity: medium
- File: `src/memory_os/toolkit/eval_runner.py:43-50`
- Called path: `src/memory_os/toolkit/eval_runner.py:187-202`

`EvalRunner.run()` computes `suite_dir = EVALS_DIR / suite_name` and checks only `suite_dir.is_dir()`. `pathlib` preserves `..` traversal and an absolute right-hand operand replaces the base path, so a caller-controlled suite name can point outside `src/memory_os/toolkit/evals`.

Concrete repro verified with the same `/private/tmp/memory_os_audit_suite_abs` suite:

```bash
PYTHONPATH=src python3 - <<'PY'
from memory_os.core.config import MemoryOSConfig
from memory_os.toolkit.eval_runner import EvalRunner
result = EvalRunner(MemoryOSConfig()).run('/private/tmp/memory_os_audit_suite_abs')
print(result['suite'])
print(result['kind'])
print(result['status'])
print(result.get('reason'))
PY
```

Observed result:

```text
/private/tmp/memory_os_audit_suite_abs
llm_judge
skipped
no LLM API key configured
```

That result proves `config.json` and `cases.jsonl` were loaded from outside `EVALS_DIR` before the suite was skipped.

Concrete failure scenario:
An automated evaluation job accepts a suite name from a branch, issue comment, or CI parameter and runs `memory_os eval run <suite>`. A caller supplies `../../../../private/tmp/memory_os_audit_suite_abs` or an absolute path. The process parses files outside the intended eval fixture directory and may leak path/existence or parse-error details through the returned error string at `eval_runner.py:52`.

Suggested fix:
- Validate suite names as slugs, not paths.
- Resolve and confine the suite directory:

```python
base = EVALS_DIR.resolve()
suite_dir = (base / suite_name).resolve()
suite_dir.relative_to(base)
```

- Reuse the same helper from `eval_export.py` so runner and exporter enforce identical boundaries.

### 3. Eval config/cases loading is unbounded and can exhaust memory or stall commands

- Severity: medium
- File: `src/memory_os/toolkit/eval_runner.py:27-28`
- Called path: `src/memory_os/toolkit/eval_runner.py:187-202`

`list_suites()` calls `len(self._load_cases(suite_dir))` for every suite. `_load_cases()` appends every parsed JSONL case to a list, and `_load_suite_config()` uses `json.load()` with no file-size limit. `run()` also loads all cases before deciding whether the suite kind is supported or skipped.

Malformed JSON is handled acceptably in `EvalRunner`: `list_suites()` catches exceptions and skips the suite, while `run()` returns an error result. The confirmed problem is resource exhaustion on large-but-valid files.

Concrete failure scenario:
A repository or writable checkout contains `src/memory_os/toolkit/evals/big/cases.jsonl` with millions of valid JSON lines, or a traversal suite from finding 2 points to such a file. Running `memory_os eval list` must parse and retain the entire file just to compute `case_count`, causing high memory use or process termination. Running `memory_os eval run big` has the same unbounded load before execution.

Suggested fix:
- Add maximum file sizes for `config.json` and `cases.jsonl` before opening.
- Add maximum line length and maximum case count.
- For `list_suites()`, count JSONL records with a streaming counter instead of materializing case objects.
- For `run()`, stream cases through the executor where possible, or fail closed when the case count exceeds a configured limit.

### 4. Review-pack misses source-file warnings for quoted git porcelain paths

- Severity: medium
- File: `src/memory_os/toolkit/review_pack.py:38`
- Called path: `src/memory_os/core/evidence.py:77-92`

`change_size_report()` and `ReviewPackBuilder.build()` depend on `EvidenceStore.changed_files()`. That helper runs `git status --porcelain`, then parses with:

```python
for line in result.stdout.splitlines():
    if len(line) > 3:
        files.append(line[3:].strip())
```

For paths that Git quotes in non-`-z` porcelain output, such as paths with spaces or newlines, the parsed filename includes the leading quote and C-style escaping. `small_batch_warnings()` then checks `f.startswith("src/")`, so quoted source paths are not classified as source files.

Concrete repro verified in a temporary git repo:

```bash
git init -q
git config user.email audit@example.invalid
git config user.name Audit
printf x > 'src/line
break.py'
printf x > 'src/has space.py'
printf x > 'src/semi;colon.py'
git add .
git commit -q -m init
printf y > 'src/line
break.py'
printf y > 'src/has space.py'
printf y > 'src/semi;colon.py'
git status --porcelain
```

Observed porcelain and current parser output:

```text
 M "src/has space.py"
 M "src/line\nbreak.py"
 M src/semi;colon.py

parsed:
[
  "\"src/has space.py\"",
  "\"src/line\\nbreak.py\"",
  "src/semi;colon.py"
]
source_files:
[
  "src/semi;colon.py"
]
```

Concrete failure scenario:
A risky patch modifies only `src/has space.py` or `src/line\nbreak.py` and does not update `test_auto.py`. `change-size` reports the changed file with quotes/escapes but `small_batch_warnings()` does not emit the intended warning: `source file(s) under src/ changed but test_auto.py was not updated`. That is security-relevant correctness drift because review-pack is supposed to flag review risk truthfully.

Shell metacharacters alone were not an execution issue in the reviewed path: `EvidenceStore.changed_files()` uses `subprocess.run(["git", "status", "--porcelain"], ...)`, so filenames such as `src/semi;colon.py` are not executed by a shell. The confirmed issue is parsing and classification of quoted/newline paths.

Suggested fix:
- Use NUL-delimited porcelain:

```python
git status --porcelain=v1 -z --untracked-files=all
```

- Parse bytes or text split on `\0`, not newlines.
- For rename/copy records, handle the old/new path pair explicitly.
- Do not call `.strip()` on filenames; preserve leading/trailing spaces.
- Feed decoded real paths into `small_batch_warnings()`, and only escape them when rendering Markdown or text output.

## Verified non-issues

- `eval_runner.py` does not write files directly.
- Malformed JSON/JSONL in `eval_runner.py` does not hang by itself: `run()` returns an error result and `list_suites()` skips the bad suite.
- Shell metacharacters in changed filenames are not executed by `review_pack.py` or `EvidenceStore.changed_files()` because git is invoked with an argv list and `shell=False`.

VERDICT: 4 issues found (1 critical/high)
