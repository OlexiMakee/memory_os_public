# Adversarial Security and Correctness Audit: Persona/Search/Exporter/Versioner/Optimizer

Scope:
- `src/memory_os/modules/persona.py`
- `src/memory_os/modules/search.py`
- `src/memory_os/modules/exporter.py`
- `src/memory_os/modules/versioner.py`
- `src/memory_os/modules/optimizer.py`

Additional called paths reviewed where required by the scope focus:
- `src/memory_os/cli.py`
- `src/memory_os/modules/compactor.py`
- `src/memory_os/modules/validator.py`
- `src/memory_os/toolkit/obsidian_exporter.py`
- `src/memory_os/core/core.py`
- `src/memory_os/core/retrieval.py`
- `src/memory_os/core/storage.py`

Review constraints honored:
- No files under `src/` or `scripts/` were edited.
- No git write commands were run.
- Findings are limited to issues confirmed by reading the actual code paths involved.

## Findings

### 1. `PolyglotExporter` can overwrite files outside its intended export directories via `node_id` path traversal

- File: `src/memory_os/modules/exporter.py:36`, `src/memory_os/modules/exporter.py:62`, `src/memory_os/modules/exporter.py:68`, `src/memory_os/modules/exporter.py:103`
- Severity: high
- Code path verified:
  - `MemoryCompactor.compact_capsules()` accepts LLM-proposed nodes that pass `EvolutionGate`, then calls `exporter.export_node(node["id"], ...)` at `src/memory_os/modules/compactor.py:421`.
  - `MemoryCompactor.compress_graph()` does the same for compression output at `src/memory_os/modules/compactor.py:604`.
  - `EvolutionGate._schema_check()` requires `id`, but does not reject path separators, `..`, absolute paths, newlines, or control characters at `src/memory_os/modules/validator.py:134`.
  - `PolyglotExporter` concatenates `node_id` into filesystem paths without resolving and confining the result.
- Concrete exploit/repro scenario:
  - A malicious or compromised task capsule can steer the compaction LLM to propose a `rule` node with `id` set to `../../README` and a plausible long summary/evidence list.
  - `EvolutionGate` accepts that shape because `id`, `type`, `summary`, and list-valued `evidence` are present and `type == "rule"`.
  - During export, `_export_to_claude()` creates `.claude/skills`, then opens `root/.claude/skills/../../README.md`, which resolves to `root/README.md`, and overwrites it with generated skill content.
  - Similar escapes are available from `.cursor/rules` and `agent_context/knowledge` because all three export paths derive directories or filenames directly from `node_id`.
- Suggested fix:
  - Validate exported node IDs before any filesystem use with the existing `memory_os.core.safe_id.validate_safe_id()` or an equivalent single-segment slug validator.
  - Resolve each final export path and require it to remain under the intended export directory, not merely under the project root.
  - Treat invalid node IDs as rejected `EvolutionGate` failures and log them to events instead of catching export exceptions and continuing silently.

### 2. `export-obsidian` can overwrite project files outside the vault via malicious node IDs

- File: `src/memory_os/toolkit/obsidian_exporter.py:41`
- Severity: high
- Code path verified:
  - The hidden CLI command `export-obsidian` calls `export_obsidian_vault(root_dir, nodes_path, edges_path)` at `src/memory_os/cli.py:1659`.
  - `cmd_export_obsidian()` passes `nodes_path = config.internal_memory_dir / "nodes.jsonl"` at `src/memory_os/cli.py:1656`.
  - `export_obsidian_vault()` reads each node from JSONL and writes `node_path = vault_dir / f"{node_id}.md"` without validating `node_id` or confining the resolved path at `src/memory_os/toolkit/obsidian_exporter.py:37` and `src/memory_os/toolkit/obsidian_exporter.py:41`.
- Concrete exploit/repro scenario:
  - If `src/memory_os/memory_graph/nodes.jsonl` contains a node with `{"id":"../../README","type":"fact","summary":"attacker content"}`, running `python3 -m memory_os export-obsidian` computes `root/data/obsidian_vault/../../README.md`.
  - That path resolves to `root/README.md`; the subsequent `open(node_path, "w", encoding="utf-8")` at `src/memory_os/toolkit/obsidian_exporter.py:93` overwrites the project README with the exported node markdown.
  - The vault delete step at `src/memory_os/toolkit/obsidian_exporter.py:18` does not mitigate this because the traversal happens after vault recreation and targets a different path.
- Suggested fix:
  - Sanitize Obsidian filenames separately from graph IDs, for example map node IDs through a safe slug function and preserve the original ID only in file content/frontmatter.
  - Resolve `node_path` and require it to stay under `vault_dir.resolve()` before opening it.
  - Reject or skip unsafe node IDs with a logged error; do not try to create parent directories for unsafe paths.

### 3. Exported Cursor/Claude frontmatter is built by raw string interpolation, so node content can break or inject metadata

- File: `src/memory_os/modules/exporter.py:41`, `src/memory_os/modules/exporter.py:43`, `src/memory_os/modules/exporter.py:105`, `src/memory_os/modules/exporter.py:108`
- Severity: medium
- Code path verified:
  - `_export_to_cursor()` writes a YAML-like frontmatter block with `description: {summary}` and optional `globs: {globs_str}` by string concatenation.
  - `_export_to_claude()` writes `name: {node_id}` and `description: {summary}` the same way.
  - `summary` originates from LLM-proposed node data in `MemoryCompactor` at `src/memory_os/modules/compactor.py:348` and is not restricted to a single line by `EvolutionGate`; `EvolutionGate._quality_check()` only checks minimum stripped length at `src/memory_os/modules/validator.py:144`.
- Concrete exploit/repro scenario:
  - A proposed node summary of `normal text\n---\n# Injected body\nAlways follow this injected instruction` passes `EvolutionGate` because it is a non-empty string longer than 20 characters.
  - `_export_to_cursor()` writes that string directly after `description:`, producing a `.mdc` file where the attacker-controlled `---` can terminate frontmatter early and turn the remaining text into rule body before the exporter writes its intended `alwaysApply` metadata.
  - For Claude skill export, the same multiline summary can produce malformed frontmatter or attacker-controlled markdown before the intended generated body, causing the consuming tool to interpret a different rule/skill shape than the exporter intended.
- Suggested fix:
  - Generate frontmatter with a structured YAML serializer such as `yaml.safe_dump()` over a dict, not raw string interpolation.
  - Reject or escape multiline values in frontmatter fields if the target tool expects single-line metadata.
  - Validate `globs` entries as strings without newlines and keep `summary` in the markdown body, not as an unescaped frontmatter scalar.

### 4. A single malformed JSONL node or edge can crash `MemorySearcher.search_memory()`

- File: `src/memory_os/modules/search.py:143`, `src/memory_os/modules/search.py:147`, `src/memory_os/modules/search.py:148`, `src/memory_os/modules/search.py:51`
- Severity: low
- Code path verified:
  - `_load_nodes()` and `_load_edges()` return raw JSON objects from `FileSystemMemoryStorage.load_jsonl()` at `src/memory_os/modules/search.py:22` and `src/memory_os/modules/search.py:27`.
  - `FileSystemMemoryStorage.load_jsonl()` validates only JSON syntax; it appends any parsed JSON object and skips only `JSONDecodeError` at `src/memory_os/core/storage.py:14`.
  - `search_memory()` then indexes required fields with `node["id"]`, `node["summary"]`, `node["evidence"]`, and `node["type"]`.
  - `traverse_graph()` indexes `edge["source"]` and `edge["target"]`.
- Concrete failure scenario:
  - If `memory/nodes.jsonl` or the internal nodes file contains a syntactically valid but schema-invalid line such as `{"id":"bad.node","type":"fact"}`, `python3 -m memory_os search bad` raises `KeyError: 'summary'` at `src/memory_os/modules/search.py:147`.
  - If an edge line omits `source` or `target`, a query that reaches traversal raises `KeyError` at `src/memory_os/modules/search.py:51`.
  - This is a correctness and local denial-of-service issue for shared or partially corrupted memory files: one bad record prevents search from returning any valid results.
- Suggested fix:
  - Validate loaded nodes and edges before searching; skip invalid records with a warning or route them through `MemoryValidator`.
  - Replace direct indexing with defensive `.get()` access where a missing optional field can be treated as empty data.
  - Keep strict schema failures visible in validation output so corruption is not silently ignored.

## Checked Files With No Confirmed Issue

### `src/memory_os/modules/search.py`

- I found no SQL interpolation in `MemorySearcher.search_memory()`: it does not query SQLite at all; it loads JSONL nodes/edges and a JSON snapshot, then uses Python substring matching.
- I found no ReDoS-prone regex in `MemorySearcher`: this file does not compile or execute regular expressions.
- The SQLite FTS paths I checked outside `MemorySearcher` use bound parameters for `MATCH`: `src/memory_os/core/core.py:239` and `src/memory_os/core/retrieval.py:21`, `src/memory_os/core/retrieval.py:30`.

### `src/memory_os/modules/exporter.py`

- No additional confirmed issue beyond the path traversal and frontmatter injection findings above.
- The JSON metadata output in `_export_to_antigravity()` uses `json.dump(...)` at `src/memory_os/modules/exporter.py:93`, so I did not find JSON syntax injection there.

### `src/memory_os/modules/persona.py`

- No confirmed YAML object-injection issue found.
- `sync_from_transcript()` treats transcript lines as JSON data, sends bounded text slices to the LLM, parses the LLM response with `json.loads()`, and writes `persona.yaml` using `yaml.safe_dump()` at `src/memory_os/modules/persona.py:76` and `src/memory_os/modules/persona.py:80`.
- I found no `yaml.load()` call in the reviewed persona path or other `src/memory_os` files; the YAML uses I found were `yaml.safe_dump()`.
- The only regex in this file, `re.sub(r'```.*?```', ...)` at `src/memory_os/modules/persona.py:52`, is not a nested-quantifier pattern and I did not find a concrete catastrophic-backtracking case for it.

### `src/memory_os/modules/versioner.py`

- No confirmed issue found.
- `PromptVersioner` is an in-memory registry only. It has no filesystem or database writes, no rollback surface, and no loop over attacker-controlled data.

### `src/memory_os/modules/optimizer.py`

- No confirmed corruption or rollback issue found.
- `RouteOptimizer.analyze_metrics()` performs a read-only aggregate query with bound parameters for `prompt_name` and `limit` at `src/memory_os/modules/optimizer.py:14`.
- `RouteOptimizer.recommend_route()` only filters the returned aggregate rows in memory and does not write optimized routes back to disk or database, so I found no path where an optimization pass can silently corrupt or lose persisted data.

VERDICT: 4 issues found (2 critical/high)
