# Adversarial CLI Audit: `src/memory_os/cli.py`

Scope: read-only audit of `src/memory_os/cli.py` as the CLI orchestration surface, including the concrete code paths it calls for the reviewed commands.

## Findings

### 1. `ide-grant` silently grants global wildcard tool permissions outside the workspace

- Severity: high
- Location: `src/memory_os/cli.py:1236`, `src/memory_os/cli.py:1241`, `src/memory_os/cli.py:1248`, `src/memory_os/cli.py:1296`
- Confirmed scenario: invoking the hidden subcommand `python3 -m memory_os ide-grant` writes to `Path.home() / ".gemini/config/config.json"` rather than the project root. It adds global wildcard grants including `unsandboxed(*)`, `write_file(*)`, `read_file(*)`, `execute_url(*)`, and `mcp(*)`. A less-trusted wrapper that can invoke this CLI can permanently weaken the user's Antigravity permission model outside `memory_os`.
- Suggested fix: remove this command from the project CLI, or gate it behind an explicit interactive confirmation plus an environment opt-in. If it must remain, restrict it to project-local config only and never add broad wildcard grants.

### 2. `context build --contract` reads arbitrary local files and prints their contents

- Severity: high
- Location: `src/memory_os/cli.py:412`, `src/memory_os/core/context_pack.py:338`, `src/memory_os/core/context_pack.py:346`, `src/memory_os/core/context_pack.py:413`
- Confirmed scenario: `cmd_context` passes `args.contract` directly to `ContextPackBuilder.build`. `_parse_contract` uses `Path(contract_path)`, accepts absolute paths, reads the file with `path.read_text(...)`, and for a non-JSON/non-heading text file assigns the entire content to `task_summary`. A temp repro with `--contract /private/tmp/memory_os_contract_secret.txt --dry-run --format markdown` printed the marker from that outside file.
- Suggested fix: resolve the contract path against `config.root_dir`, reject absolute paths unless explicitly allowed, and require the resolved path to stay under allowed project directories such as `specs/` or `agent_context/context_packs/`. Return a clean error for rejected paths.

### 3. `evidence --task` allows path traversal and writes evidence bundles outside the project

- Severity: medium
- Location: `src/memory_os/cli.py:441`, `src/memory_os/cli.py:455`, `src/memory_os/cli.py:480`, `src/memory_os/core/evidence.py:43`, `src/memory_os/core/evidence.py:53`
- Confirmed scenario: `cmd_evidence` passes `args.task` directly into `EvidenceStore`. `bundle_path()` returns `self.evidence_dir / task_id / "bundle.json"` without validation. With a root under `/private/tmp`, `evidence init --task ../../../memory_os_audit_escape` created `/private/tmp/memory_os_audit_escape/bundle.json`, outside the configured project root.
- Suggested fix: validate task IDs with a strict slug pattern such as `^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$`, reject path separators and `..`, and after resolving the final path verify it is still under `agent_context/evidence`.

### 4. `spec init --id` allows path traversal and writes spec files outside `specs/`

- Severity: medium
- Location: `src/memory_os/cli.py:331`, `src/memory_os/cli.py:334`, `src/memory_os/toolkit/spec_workflow.py:214`, `src/memory_os/toolkit/spec_workflow.py:218`, `src/memory_os/toolkit/spec_workflow.py:227`
- Confirmed scenario: `cmd_spec` passes `--id` as `feature_id` to `SpecManager.init_feature`. The code builds `feature_root = self.specs_dir / feature_id` and writes `spec.md`, `plan.md`, `tasks.md`, and `checklist.md` there. A temp repro with `spec init Title --id ../../memory_os_spec_escape2` wrote those files under `/private/tmp/memory_os_spec_escape2`, outside the root's `specs/` directory.
- Suggested fix: use the same strict slug validation for explicit feature IDs that `_slug()` applies to generated IDs, reject separators and `..`, and enforce `feature_root.resolve().is_relative_to(self.specs_dir.resolve())` before creating directories.

### 5. `run <status|resume|complete|abort> run_id` can read and modify external `record.json` files

- Severity: medium
- Location: `src/memory_os/cli.py:672`, `src/memory_os/cli.py:674`, `src/memory_os/cli.py:677`, `src/memory_os/cli.py:687`, `src/memory_os/toolkit/run_records.py:45`, `src/memory_os/toolkit/run_records.py:55`
- Confirmed scenario: `RunRecordStore.record_path()` returns `self.runs_dir / run_id / "record.json"` without validating `run_id`. A temp repro created `/private/tmp/memory_os_run_escape/record.json`, ensured the root's `agent_context/runs` directory existed, then invoked `run complete ../../../memory_os_run_escape --outputs '{"pwn":true}'`. The command returned success and modified the outside JSON file's status and outputs.
- Suggested fix: validate `run_id` before load/save, reject path separators and `..`, and enforce resolved-path confinement under `agent_context/runs`.

### 6. `--root` is ignored for config-backed commands when the target root has no config file

- Severity: medium
- Location: `src/memory_os/cli.py:2586`, `src/memory_os/cli.py:2588`, `src/memory_os/cli.py:2593`, `src/memory_os/cli.py:2597`
- Confirmed scenario: `main()` only uses `--root` to find `<root>/memory_os.config.json`. If that file does not exist, it falls back to `Path.cwd() / "memory_os.config.json"` instead of treating `--root` as the config root. Commands that use `config.root_dir`, including `evidence`, `context`, `review-pack`, `run`, `stats`, and `resources`, can therefore read/write the current repository while the caller believes `--root /some/sandbox` is isolating the operation.
- Suggested fix: when `--root` is provided and no config file exists there, instantiate defaults with root-derived paths rather than cwd-derived paths, or fail with a clean error requiring `memory_os.config.json` under the requested root.

### 7. `stats` and other DB-backed commands allow arbitrary DB paths through unvalidated config

- Severity: medium
- Location: `src/memory_os/cli.py:1978`, `src/memory_os/cli.py:1309`, `src/memory_os/core/config.py:102`, `src/memory_os/core/config.py:105`, `src/memory_os/core/core.py:17`, `src/memory_os/core/core.py:22`
- Confirmed scenario: the top-level `--config` accepts any path, `MemoryOSConfig.db_path` resolves `db_path` from that JSON without checking project confinement, and `MemoryOS.__init__` creates the parent directory and connects to that path. A config with an absolute `db_path` or a relative `../../outside.db` makes `stats` and other DB-backed commands open or create SQLite files outside the project, differing from the documented canonical `memory/memory_os.db`.
- Suggested fix: reject absolute `db_path` values by default, resolve relative DB paths against `root_dir`, and require the resolved path to stay under an approved project data directory. If external DBs are a deliberate feature, require an explicit `--allow-external-db` opt-in.

### 8. `pipeline --notion-key` exposes secrets in terminal output

- Severity: medium
- Location: `src/memory_os/cli.py:882`, `src/memory_os/toolkit/pipeline.py:130`, `src/memory_os/toolkit/pipeline.py:37`, `src/memory_os/toolkit/pipeline.py:153`
- Confirmed scenario: `cmd_pipeline` passes `args.notion_key` into `PipelineRunner.run`. The runner interpolates the token into a command string and prints it both during execution (`CMD : ...`) and dry-run (`memory_os notion-sync --api-key ...`). A CI log or less-trusted caller capturing stdout receives the raw Notion integration token.
- Suggested fix: do not put secrets into printable command strings. Pass secrets through environment variables or structured arguments, redact known secret-bearing flags in logs, and make dry-run output show `--api-key [REDACTED]`.

### 9. Some CLI paths still raise unhandled tracebacks with full local paths

- Severity: low
- Location: `src/memory_os/cli.py:669`, `src/memory_os/cli.py:676`, `src/memory_os/cli.py:1372`, `src/memory_os/cli.py:2600`
- Confirmed scenario: `cmd_rag` writes to `root / "agent_context" / "active_memory.yaml"` but never defines `root`. With a temp root containing a matching node, `python3 -m memory_os --root <tmp> rag foo` exited with a Python traceback showing full local source paths and `NameError: name 'root' is not defined`. Separately, `cmd_run` calls `json.loads(args.inputs)` and `json.loads(args.outputs)` without catching `JSONDecodeError`; malformed JSON reaches `main()`'s raw `args.func(...)` call and produces the same style of traceback.
- Suggested fix: define `root = Path(args.root).resolve()` or use `config.root_dir` in `cmd_rag`; wrap `cmd_run` JSON parsing in `try/except json.JSONDecodeError`; and add a top-level CLI exception boundary that converts expected user-input failures into concise errors without stack traces.

## Checked Surfaces With No Confirmed Issue

- `cmd_check_updates` uses fixed `git` argument lists; I found no user-controlled shell invocation there.
- `cmd_daemon start` passes `--log-file` through a `subprocess.Popen` list rather than a shell string; I found no shell injection in that path.
- `cmd_evidence add-command` intentionally runs the command supplied after `--`; it uses `subprocess.run(list(command), shell=False)`. I did not count this as shell injection, but it remains an intentional arbitrary-command feature.
- `cmd_context --task` sanitizes the output slug with `re.sub(r"[^a-z0-9]+", "-", ...)` before writing context packs; I found no traversal through `--task` alone.
- `cmd_run start --workflow` generates a run ID through `_run_id_prefix()` plus a UUID suffix; I found no traversal through newly-created run IDs. The traversal applies to caller-supplied `run_id` in status/resume/complete/abort.
- `cmd_ingest file` reads arbitrary local paths by design according to its help text ("external document"); I found no subprocess, shell, `eval`, or `exec` path from that argument in the reviewed adapter.

VERDICT: 9 issues found (2 critical/high)
